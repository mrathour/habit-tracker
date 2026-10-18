# Chrome extension notes (Phase 1)

Findings from reading the author's Chrome extension **WebNotes** at `C:\Users\LENOVO\Documents\JS\myNotionNotes` (read only, 2026-10-17), plus the auth design proposed for the desktop app. File references are relative to that folder.

## 1. What the extension is

WebNotes captures parts of web pages, turns them into notes, and **writes** them to Notion. It has three parts:

| Part | Files | Role |
|---|---|---|
| Chrome extension (Manifest V3) | `extension/background.js`, `popup.js`, `content.js`, `manifest.json` | UI, element picker, starts Notion OAuth |
| Local FastAPI backend on `http://localhost:8000` | `backend/main.py`, `backend/notion_sync.py` | OAuth code exchange, every Notion API call, file capture |
| Helper scripts | `sync_notes.py`, `notes_db.py`, `hooks/notion_sync.py` | AI note generation, a SQLite tracker, retrying Notion syncs |

All Notion API calls go through the local backend. Its CLAUDE.md says Notion blocks `chrome-extension://` origins. This doesn't affect a desktop app: Python calls Notion directly, without CORS.

## 2. Secrets found (masked)

| Location | What | Tracked by git? |
|---|---|---|
| `backend/.env` | `NOTION_CLIENT_ID` and **`NOTION_CLIENT_SECRET`** (the OAuth client secret) in plain text | No (gitignored), and never in history |
| `backend/notion_config.json` | `token`: a **live Notion access token** in plain text, plus the target page or database ID | No (gitignored), and never in history |

I copied neither value anywhere. The one history match for `NOTION_CLIENT_SECRET=` is the `...` placeholder in their CLAUDE.md. The access token is also kept in `chrome.storage.sync` (see 3.3).

## 3. Authentication

### 3.1 Flow

The extension uses **OAuth 2.0 authorization code flow with a Notion public integration**. The client secret is kept on a backend.

1. **Popup.** "Connect to Notion" sends `NOTION_AUTH` to the service worker (`popup.js:206-220`).
2. **Authorize URL.** `background.js:199-213` builds `https://api.notion.com/v1/oauth/authorize?client_id=…&redirect_uri=https://<extension-id>.chromiumapp.org/&response_type=code&owner=user&state=<random UUID>`. It opens the URL with `chrome.identity.launchWebAuthFlow`.
3. **Callback.** `background.js:215-221` checks that `state` matches, a good CSRF guard, and reads `code`.
4. **Code to backend.** The code and `redirect_uri` are POSTed to the local backend at `/notion/token` (`background.js:223-232`).
5. **Token exchange.** The backend (`main.py:290-328`) calls `POST https://api.notion.com/v1/oauth/token`:
   - It authenticates with HTTP Basic, `base64(client_id:client_secret)`.
   - The body is `{grant_type: "authorization_code", code, redirect_uri}`.
6. **Response.** The backend returns **only** `access_token`, `workspace_name` and `workspace_id`. It throws away `refresh_token`, `bot_id`, `owner` and `workspace_icon`.

### 3.2 Client secret and backend

- The secret lives only in `backend/.env` on the user's machine (`main.py:19-22`), so it never reaches the browser.
- The "backend" is a local server that each user must run. The README tells every user to **create their own Notion integration** and paste their own client ID and secret. That doesn't scale to other users, and it's why this design can't be reused as-is for a distributed app.

### 3.3 Token storage

- **`chrome.storage.sync`** (`background.js:236-240`) holds `notion_token`, `notion_workspace` and `notion_workspace_id`. This storage is unencrypted on disk and is **synced to the user's Google account** across every Chrome profile that signs in.
- **`backend/notion_config.json`** (`notion_sync.py:22-23`) holds the token in plain text. The popup sends the token there in a JSON body to `/notion/config` (`popup.js:16-22`, `popup.js:245-248`).
- For search, the popup sends the token to the backend in an `Authorization` header (`popup.js:7-14`).

### 3.4 Refresh, expiry and logout

- **No refresh.** The refresh token is discarded, so the token can't be renewed.
- **No handling of 401 or expired tokens.** A failed call surfaces as a generic error.
- **No logout or disconnect.** The token is never revoked, and the stored copies are never removed. "Change target" only clears the target.

## 4. Notion API endpoints called

Every call sends **`Notion-Version: 2022-06-28`** (`notion_sync.py:10`, `main.py:352`, `main.py:390`). The `oauth/authorize` and `oauth/token` calls send no version header.

| # | Method and endpoint | Where | Purpose | Read or write |
|---|---|---|---|---|
| 1 | `GET /v1/oauth/authorize` (browser) | `background.js:203` | Start OAuth | n/a |
| 2 | `POST /v1/oauth/token` | `main.py:303` | Exchange the code for a token | n/a |
| 3 | `POST /v1/search` (`page_size: 100`, sorted by `last_edited_time`) | `main.py:348` (`/notion/targets`) | List pages and databases. **Dead code:** the popup never calls this route. | Read |
| 4 | `POST /v1/search` (`query`, `page_size: 20`) | `main.py:386` (`/notion/search`) | Target picker search | Read |
| 5 | `GET /v1/databases/{id}` | `notion_sync.py:285` | Find the title property's name | Read |
| 6 | `POST /v1/pages` | `notion_sync.py:318` | Create a note page with its first 100 blocks | **Write** |
| 7 | `PATCH /v1/blocks/{id}/children` | `notion_sync.py:331`, `381` | Append more blocks, in chunks of 100 | **Write** |
| 8 | `GET /v1/blocks/{id}/children` | `notion_sync.py:350` | List the blocks to clear before an update | Read |
| 9 | `DELETE /v1/blocks/{id}` | `notion_sync.py:364` | Archive old blocks | **Write** |
| 10 | `GET /v1/pages/{id}` | `notion_sync.py:389` | Read a page URL after an update | Read |

**What this means for the desktop app:**
- Only calls 1–5 match what we need. Calls 6, 7 and 9 are writes, which the hard rules forbid.
- None of the calls queries a database's rows. The Work Log query (filter, sort, pagination) has to be written from scratch.

## 5. Pagination, rate limits, retries and errors

**Pagination**
- **Done once:** only `_clear_page_children` loops with `start_cursor`, `has_more` and `next_cursor` at `page_size: 100` (`notion_sync.py:344-361`). The loop is correct.
- **Search reads a single page.** It returns 20 or 100 results and ignores `has_more` (`main.py:379`, `355-358`). A workspace with more targets than that can't see them all.
- **Block writes are chunked** at Notion's 100-children limit (`notion_sync.py:306`, `375`).

**Rate limits**
- **None.** Nothing handles HTTP 429 or `Retry-After`, and nothing throttles requests.
- Deleting blocks fires one request per block in a tight loop (`notion_sync.py:363-364`), so large pages can hit Notion's rate limit.

**Retries**
- **No HTTP-level retries.** The only retry is at the application level: notes whose Notion sync failed stay flagged in SQLite (`notion_synced = 0`) and are re-sent on the next run (`sync_notes.py:80-107`, `notes_db.py:110-116`).

**Error handling**
- **Status checks**
  - Page creation, the final update append and listing children raise `RuntimeError` with the status and body.
  - The backend converts these to HTTP errors, and `notes_db` records them (`main.py:628-630`).
- **Silent failures**
  - **Chunk appends after page creation are never checked** (`notion_sync.py:330-335`). A failure leaves a half-written page that is still marked as synced.
  - **Block deletes are never checked** (`notion_sync.py:363-364`).
  - `_get_title_prop_name` falls back to the property name `"title"` on any error (`notion_sync.py:289-290`). That hides permission problems.
- **Fragile error parsing**
  - On a non-200 token exchange, `res.json()` is called with no guard (`main.py:316-321`). A non-JSON error body would crash with a 500.
  - Search errors collapse to "Failed to fetch from Notion" or "Failed to search Notion", which drops Notion's own error code.
- **Timeouts**
  - `notion_sync.py` uses a 30 s timeout.
  - The `main.py` calls use httpx's default 5 s timeout.
- **Swallowed failures**
  - The PostToolUse hook ignores an unreachable backend (`hooks/notion_sync.py:46-48`).
- **User-facing messages are good**
  - Every UI path reports "Server unreachable — is the Python server running?" or Notion's detail text.

## 6. Reading property values

The extension reads almost no property values. It writes pages, and never reads database rows.

| Property type | What the extension does |
|---|---|
| **Title** | Joins `plain_text` across the rich-text array, or returns "Untitled" if empty. It does this for page titles and database titles in search results (`main.py:333-339`). Worth porting. |
| **Database schema** | Finds the property whose `type == "title"` (`notion_sync.py:291-293`). |
| **Date, number, relation, unique ID** | Never read. |
| **Time zones** | Never applied to Notion data. Local bookkeeping uses UTC-aware `datetime.now(tz=timezone.utc)` in `notes_db.py` (good). Capture files use naive local `datetime.now()` (`main.py:124`). |

So Phase 5 needs its own property readers, based on the Notion reference ([page property values](https://developers.notion.com/reference/page-property-values)):

**Date**: `{"start", "end", "time_zone"}`.
- `start` is ISO 8601, either a date only (`2026-10-17`) or a date-time.
- A date-time either carries a UTC offset (`Z`, `+00:00`, `+05:30`) or has **no offset, in which case `time_zone` gives an IANA zone** such as `Asia/Kolkata`.
- Rules for the parser:
  - A date only means **Missing time** (section 5 of PLAN.md).
  - A date-time with an offset is converted to UTC.
  - A date-time without an offset is localised with `zoneinfo.ZoneInfo(time_zone)` first, then converted to UTC.
  - **Windows has no system IANA database, so the app must depend on the `tzdata` package** for `zoneinfo` to work there.
- `end` inside one date property marks a range. The Work Log uses two separate properties, so the mapper reads only `start` from each. If a mapped date property ever holds a range, `end` is ignored and recorded as an extra-field detail.

**Title and rich text**
- Join `plain_text` across the array. An empty array means a blank name, which is not an issue.
- Mentions are capped at 25 per value in page responses. Text length isn't capped.

**Number**: a JSON number or `null`.

**Unique ID**: `{"prefix", "number"}`. Either field can be `null`. The display form is `PREFIX-number`, or just `number` when there is no prefix.

**Relation**
- An array of `{"id"}`, with **`has_more: true` when there are more than 25 references**.
- Parent Task is limited to 1 relation, so it's unaffected.
- A relation chosen as an extra field must page through `GET /v1/pages/{page_id}/properties/{property_id}` to get every reference.

**Page metadata**: `last_edited_time` has minute precision, as PLAN.md 6.1 already accounts for. `created_time` is UTC.

## 7. What to port and what not to copy

### 7.1 Worth porting (as patterns, re-implemented in Python)

| Piece | Source | Port as |
|---|---|---|
| OAuth `state` generation and check | `background.js:201`, `215-218` | Same idea in the desktop flow, plus a code verifier (section 8) |
| Basic-auth token exchange | `main.py:298-314` | Moves into the token service, extended with refresh and revoke |
| Title extraction with an "Untitled" fallback | `main.py:333-339` | `app/notion/` helper for the database picker and task names |
| `start_cursor` / `has_more` loop | `notion_sync.py:344-361` | A generic paginator (or `notion_client.helpers.iterate_paginated_api`) |
| Background thread feeding a queue, consumed by the UI | `main.py:439-479` | Sync progress events pushed to pywebview |
| Persisting the last failure so it survives a dismissed message | `notes_db.py:134-150` | The "failed with a clear reason" sync state in PLAN.md 6.4 |
| Treating "exit 0 but `is_error`" as a failure | `sync_notes.py:52-69` | Never mark a sync successful unless every page was confirmed |

### 7.2 Must not be copied

| Problem | Where | Why | Desktop app does instead |
|---|---|---|---|
| `Notion-Version: 2022-06-28` | `notion_sync.py:10`, `main.py` | Before **data sources**. The current version is **2026-03-11** ([versioning](https://developers.notion.com/reference/versioning)). Since [2025-09-03](https://developers.notion.com/docs/upgrade-guide-2025-09-03), rows are queried via `POST /v1/data_sources/{id}/query`, and old-version calls fail on multi-source databases. | Pin `2026-03-11` and use the data-source endpoints |
| Write endpoints (`POST /pages`, `PATCH`/`DELETE /blocks`) | `notion_sync.py` | Hard rule: never write to Notion | The integration asks only for **Read content**, so Notion itself blocks writes |
| Token in `chrome.storage.sync` and a plain-text JSON file, sent in request bodies | `background.js:236`, `notion_sync.py:22`, `popup.js:16-22` | Leaks to disk and syncs to a cloud account | `keyring` (Windows Credential Manager) only; never logged |
| Client secret in a local `.env` that every user must provide | `backend/.env`, README | Not distributable, and the secret sits on every machine | A hosted token service keeps the one secret (section 8) |
| Discarding `refresh_token`; no 401 handling, no logout, no revoke | `main.py:323-328` | Sessions can't be renewed or ended cleanly | Store the token pair, refresh on 401, revoke on logout |
| No 429 / `Retry-After` handling, no backoff, no throttle | everywhere | Breaks on large syncs | `notion-client` 3.x retries on 429 and 5xx with `Retry-After` and backoff, plus our own ~3 req/s limiter (PLAN.md 6.4) |
| Unchecked HTTP responses (appends, deletes) | `notion_sync.py:330-335`, `363-364` | Partial failures are reported as success | Check every response, and fail the sync if any page fetch fails |
| Single-page search | `main.py:379` | Hides databases | Paginate search fully in the database picker |
| Unguarded `res.json()` on errors; default 5 s timeouts | `main.py:316`, `main.py:302` | Crashes or spurious timeouts | Typed `APIResponseError` handling and explicit timeouts |
| `ALTER TABLE` in try/except, plus a hard-coded one-off data fix | `notes_db.py:31-59` | Unversioned and unrepeatable migrations | Numbered migrations tracked by `schema_version` (PLAN.md 11) |
| Naive local `datetime.now()` | `main.py:124` | Ambiguous times | UTC everywhere, local only for display |
| Localhost HTTP server with `allow_origins=["*"]` | `main.py:31-36` | Any website can call it (see 7.3) | No local server at all (pywebview JS bridge, as PLAN.md 10 says). The OAuth loopback listener binds `127.0.0.1` only, for one request, and checks `state`. |

### 7.3 Security issue in the extension (for the author; not changed)

The backend accepts requests from **any origin** (`main.py:31-36`). A web page you visit could therefore send requests to `http://localhost:8000` while the backend is running. Chrome's Private Network Access rules may block some of these, but not reliably. That page could:
- **Replace the token and target.** `POST /notion/config` (`main.py:418-422`) accepts any token and target with no checks.
- **Upload any `.md` file on disk** to whatever target is configured. `POST /notion/sync` (`main.py:591-633`) does this.

Chained together, a malicious page could send local Markdown files to the attacker's own Notion. It could also start AI note runs through `/make-notes`.

**Suggested fix:**
- Restrict CORS to `chrome-extension://<your-id>`.
- Require a shared secret header on every route.
- Limit `/notion/sync` paths to the `notes/` folder.

I haven't changed anything in the extension.

## 8. Proposed auth design for the desktop app

**Status:** approved on 2026-10-18 with additions. PLAN.md section 12 is now the authoritative version; this section records the original proposal.

This responds to PLAN.md section 12: support other users' workspaces through OAuth, never embed the client secret, read-only access, tokens in Credential Manager, and logout.

### 8.1 Options compared

| | A. Internal integration token | B. Public OAuth, secret in the app | C. Public OAuth, local backend with the user's own secret (the extension's design) | **D. Public OAuth with a hosted token service** |
|---|---|---|---|---|
| How a user connects | Creates their own integration in Notion, copies its token into the app, and shares the database with it | "Connect to Notion" in the browser | Creates their own public integration, then sets up a client ID and secret | **"Connect to Notion" in the browser** |
| Works for other users | Yes, but several manual steps for each user | Yes | No; every user becomes an integration developer | **Yes, with one click** |
| Client secret | None | **Shipped in the installer, so extractable** (violates 12) | On each machine | **Only in the hosted service** |
| Token renewal | Doesn't expire | Refresh possible | Refresh possible | **Refresh through the service** |
| Logout and revocation | User deletes the integration in Notion | Revoke possible | Revoke possible | **Revoke through the service** |
| Dependency outside the app | None | None | None | A small stateless service must be online to connect, refresh and revoke. Syncing goes straight to Notion. |
| Read-only enforced by Notion | Yes, if the user ticks only "Read content" (user-controlled) | Yes | Yes | **Yes, set once in our integration** |
| Fits PLAN.md 12 | Partly (no OAuth) | **No** | **No** (not distributable) | **Yes** |

### 8.2 Recommendation: D, with A as an advanced alternative

**Recommended: D, public OAuth through a small hosted token service.** It is the only option that gives one-click connect for every user, keeps the secret off every machine, and supports renewal and revocation.

**Also offered: A, in Settings → Advanced, as "Use an internal integration token".** It is for workspaces where an admin blocks public integrations, and for anyone who doesn't want a third-party service involved. It is a full second path, not a stopgap: both paths end with a token in Credential Manager, and the rest of the app doesn't care which path produced it.

### 8.3 How D works

**One-time setup (by the author)**
- **Public integration in Notion's developer portal:**
  - name "Habit Tracker";
  - capabilities: **Read content only** (no insert, update or comments; user information not requested);
  - installation scope: **any workspace**. Notion says this **can't be changed after creation**, so it must be right the first time, or other users can't connect later.
  - The portal may ask for website, privacy policy and terms URLs. These can be served by the token service itself.
  - This is a separate integration from WebNotes, which needs write access.
- **Token service:** a small stateless HTTPS service, for example a Cloudflare Worker. Its folder would be `service/` in this repo. It holds the client ID and secret as platform secrets and has four routes:
  - `GET /callback`: Notion's registered redirect URI;
  - `POST /refresh`;
  - `POST /revoke`;
  - `GET /health`.

  It stores nothing, logs no tokens, and rate-limits each IP address.

**Connect flow (identical for the author and later users)**
1. **Prepare.** The app creates a random `state` and a one-time **X25519 key pair**. It starts a listener on `127.0.0.1` at a random free port, for a single request with a 5-minute timeout.
2. **Open the browser.** The app opens the system browser at Notion's authorize URL, with `owner=user` and `redirect_uri` set to the service's `/callback`. The `state` parameter carries `{nonce, loopback port, public key}`.
3. **Consent.** The user picks their workspace in Notion and **shares the Work Log database**.
4. **Exchange.** Notion redirects to the service's `/callback`, which exchanges the code using the secret.
5. **Hand back.** The service encrypts the token response (`access_token`, `refresh_token`, `bot_id`, `workspace_id`, `workspace_name`) to the app's public key. It redirects the browser to `http://127.0.0.1:<port>/done?state=…&payload=<ciphertext>`.
   - The plain token never appears in a URL, the browser history or the service's storage.
   - The browser then shows a "You can close this tab" page.
6. **Store.** The app checks `state`, decrypts with its private key, and discards the key pair. It saves the token pair in **Credential Manager via `keyring`**, as service `HabitTracker` and account `notion`, in a small JSON blob well under the 2,560-byte limit. Workspace name and ID go to `settings`.
7. **Pick the database.** The picker paginates `POST /v1/search`, filtered to **data sources** (API 2026-03-11).
   - It stores `database_id` and the new **`data_source_id`** key.
   - Rows are queried with `POST /v1/data_sources/{data_source_id}/query`.

**During use**
- Every request goes **straight from the app to `api.notion.com`** with the access token. The service is not involved.
- **On a 401:**
  - the app calls the service's `/refresh` once;
  - it saves the **new token pair** before retrying, because Notion rotates refresh tokens;
  - it retries the request.
- **If refresh fails** (`invalid_grant`), the app shows a "Reconnect to Notion" state and keeps the local data readable offline (PLAN.md 6.4 states).

**Logout (PLAN.md 12)**
1. The app calls the service's `/revoke` (`POST /v1/oauth/revoke`).
2. It deletes the keyring entry, even if the revoke call fails.
3. It asks whether to keep or clear the local data.

**Edge cases built in**
- **Busy port:** the app picks another random port.
- **Browser closed:** the listener times out and the app returns to the Connect screen.
- **Bad request to the listener:** a `state` mismatch or a second request is rejected.
- **Service down:** the app shows a clear message and offers the internal-token path.
- **Database not shared:** if the user didn't share the Work Log during consent, the picker is empty. It explains how to add the connection in Notion and has a "Re-run connect" button.

**Why the service callback instead of a localhost redirect URI**

Notion matches redirect URIs exactly. Third-party docs report it allows plain `http` only for `localhost`, and rejects ports that weren't registered in advance. That would tie the app to fixed ports that can be busy. Using the service's HTTPS callback plus an encrypted loopback hand-back avoids both problems, and the tokens are never readable in transit outside TLS.

### 8.4 Library support (verified)

`notion-client` 3.1.0 ([ramnes/notion-sdk-py](https://github.com/ramnes/notion-sdk-py)) has:
- `data_sources.query`;
- `oauth.token` / `refresh_token`, `oauth.introspect` and `oauth.revoke`;
- pagination helpers;
- automatic retries on 429 and 5xx with `Retry-After` and exponential backoff.

It defaults to `Notion-Version: 2025-09-03`. We will set `notion_version="2026-03-11"`.

### 8.5 PLAN.md changes this would need (made only after your approval, in this PR)

- **12. Authentication:** replace the open question with the design above.
- **10. Tech stack:**
  - `notion-client` ≥ 3.1 pinned to `Notion-Version: 2026-03-11`;
  - `tzdata` for time zones on Windows;
  - the `service/` token service (platform to confirm).
- **6.4 Mechanics:** rows come from the data-source query endpoint. Retries come from `notion-client`, plus our own request-rate limiter.
- **11. Local data model:** add `data_source_id` and `workspace_id` / `workspace_name` to `settings`.
- **14. Project layout:** add `service/`.
- **15. Phase 3 (Connect):** also build and deploy the token service, create the public integration, and add the internal-token path.
- **Decisions log:** one row for the auth design and one for the API version.

## Sources

- Notion authorization guide: https://developers.notion.com/docs/authorization
- Notion API versioning (latest 2026-03-11): https://developers.notion.com/reference/versioning
- Upgrade guide 2025-09-03 (data sources): https://developers.notion.com/docs/upgrade-guide-2025-09-03
- Upgrade guide 2026-03-11: https://developers.notion.com/docs/upgrade-guide-2026-03-11
- Revoke token: https://developers.notion.com/reference/revoke-token
- Page property values: https://developers.notion.com/reference/page-property-values
- notion-sdk-py: https://github.com/ramnes/notion-sdk-py
- Localhost redirect rules (third-party): https://docs.allauth.org/en/latest/socialaccount/providers/notion.html
