# OAuth hand-off protocol (version 1)

How the token service (`service/`) returns the result of a Notion sign-in to the desktop app, so the tokens are never readable outside the app (`PLAN.md` 12.3). The Worker (`service/src/crypto.ts`) and the app (`app/notion/handoff.py`) implement this document. Shared test vectors in `service/test/fixtures/handoff-v1.json` prove the two agree.

All binary values are **base64url without padding** (RFC 4648 §5). All times are **Unix seconds, UTC**.

## 1. Start

The app generates a one-time **X25519** key pair and opens a loopback listener on `127.0.0.1` at a random free port. It then sends:

```
POST /start
Content-Type: application/json

{"port": 52731, "public_key": "<32-byte X25519 public key>"}
```

- `port`: an integer from 1024 to 65535.
- `public_key`: exactly 32 bytes when decoded.

The Worker replies:

```json
{
  "state": "<signed state>",
  "authorize_url": "https://api.notion.com/v1/oauth/authorize?...",
  "server_time": 1792310439
}
```

- `server_time` lets the app correct for a wrong PC clock when it checks expiry (§4).
- `authorize_url` is Notion's authorize URL with the Worker's `client_id`, `redirect_uri`, `response_type=code`, `owner=user` and this `state`. The app opens it in the system browser.

## 2. State

The state ties Notion's callback to one app instance and one key.

```
claims  = {"v": 1, "n": <32 random bytes>, "p": <port>, "k": <app public key>, "e": <issued + 600>}
encoded = base64url(UTF-8 JSON of claims)
state   = encoded + "." + base64url(HMAC-SHA256(STATE_SIGNING_KEY, ASCII(encoded)))
```

- `STATE_SIGNING_KEY` is a Cloudflare secret holding 32 random bytes, base64url-encoded.
- On `/callback` the Worker accepts the state only if:
  - it has exactly two parts;
  - the HMAC matches (constant-time comparison);
  - `v` is 1;
  - `e` is in the future.
- The state is valid for 10 minutes, covering the time the user spends in Notion's consent screen.

## 3. Result envelope

After Notion redirects to `/callback`, the Worker always produces a result:
- **success:** the token response;
- **failure:** an error code.

It encrypts the result to the app's key and redirects the browser to:

```
http://127.0.0.1:<p>/done?state=<state>&payload=<envelope>
```

Encryption:

1. Generate an ephemeral X25519 key pair `(e_priv, e_pub)`.
2. Compute `shared = X25519(e_priv, k)`, where `k` is the app's public key from the state.
3. Derive the key: `key = HKDF-SHA256(ikm = shared, salt = e_pub ‖ k, info = "habit-tracker handoff v1", length = 32)`.
4. Pick `nonce` as 12 random bytes.
5. Compute `ciphertext = AES-256-GCM(key, nonce, plaintext, aad = ASCII(state))`. The 16-byte tag is appended.
6. Build `envelope = base64url(0x01 ‖ e_pub ‖ nonce ‖ ciphertext)`.

The plaintext is UTF-8 JSON. On success:

```json
{
  "v": 1,
  "exp": 1792310559,
  "result": "ok",
  "token": {
    "access_token": "…",
    "refresh_token": "…",
    "bot_id": "…",
    "workspace_id": "…",
    "workspace_name": "…",
    "workspace_icon": "…"
  }
}
```

On failure:

```json
{"v": 1, "exp": 1792310559, "result": "error", "error": "access_denied"}
```

`exp` is the time of encryption plus 120 seconds. The token object never includes Notion's `owner` (user information) or `duplicated_template_id`. `workspace_name` and `workspace_icon` may be `null`.

Error codes:

| Code | Meaning |
|---|---|
| `access_denied` | The user cancelled or declined in Notion. |
| `notion_error` | Notion returned another error on the redirect, or rejected the code exchange. |
| `notion_unreachable` | The code exchange failed with a network error, a timeout or a 5xx. |
| `server_misconfigured` | The Worker is missing its client ID or secret. |

If the state itself is missing, malformed, tampered with or expired, the Worker can't trust the port or key in it. It shows an error page in the browser instead of redirecting, and the app's listener times out (5 minutes) or the user cancels in the app.

## 4. Accepting the result (app)

The listener serves only `GET /done`.
- **Any other path** (for example `/favicon.ico`) gets `404` and doesn't count as the hand-off.
- **A `/done` request whose `state` doesn't equal the state the app received from `/start`** gets `400` and is ignored. A stray local request therefore can't end the sign-in.

The first `/done` request with the right state is the hand-off.

1. The listener stops accepting requests.
2. The app decrypts the envelope with its private key. It checks:
   - the version byte is `0x01`;
   - the lengths are right;
   - the GCM tag verifies with `aad = state`;
   - the plaintext's `v` is 1.
3. **The private key is destroyed after this one attempt, whether it succeeded or failed.** A replayed, copied or late envelope can therefore never be decrypted.
4. The app checks expiry with the server's clock: `exp > now + (server_time − local time at /start)`. A wrong PC clock can't reject a valid hand-off or accept a stale one.
5. On `result: ok`, the token pair is written to Credential Manager before anything else uses it.

The browser gets a small "You can close this tab" page (or one explaining the error). That page contains no secrets.

## 5. Why it's built this way

- **The client secret stays in the Worker.** Notion's redirect URI is the Worker's HTTPS `/callback`, because a desktop app can't keep a secret.
- **Readable only by the app.** Only ciphertext passes through the browser, its history and its address bar. Only the app instance that called `/start` holds the private key, so only it can read the result.
- **Bound to this sign-in.** The state is the GCM associated data, so an envelope can't be moved to another sign-in.
- **No server storage needed.** The HMAC-signed state with an expiry means the Worker needs no storage to recognise its own sign-ins (`PLAN.md` 12.2).
