# Token service: setup and deploy

The token service (`service/`) is a Cloudflare Worker. It serves the public pages and handles the OAuth routes for "Connect to Notion" (`PLAN.md` 12.2, `docs/handoff-protocol.md`). It stores nothing and logs no tokens.

All commands are PowerShell, run from `C:\Users\LENOVO\Documents\JS\habit-tracker\service`.

## Configuration

| Name | Kind | Where it's set | Value |
|---|---|---|---|
| `NOTION_CLIENT_ID` | Plain variable (public) | `wrangler.toml` `[vars]` | The public connection's OAuth client ID |
| `NOTION_API_BASE` | Plain variable | `wrangler.toml` `[vars]` | `https://api.notion.com` (tests and local runs point it at a fake Notion) |
| `NOTION_CLIENT_SECRET` | **Secret** | `npx wrangler secret put NOTION_CLIENT_SECRET` | The public connection's OAuth client secret |
| `STATE_SIGNING_KEY` | **Secret** | `npx wrangler secret put STATE_SIGNING_KEY` | 32 random bytes, base64url (command below) |
| `OAUTH_LIMITER`, `PAGE_LIMITER` | Rate-limit bindings | `wrangler.toml` | 20 and 120 requests a minute per IP |

Secrets exist only in Cloudflare. They are never written to the repository, a file, CI or a log.
- **Set them yourself, in your own PowerShell window.** Don't paste them into a chat, an issue or a pull request.
- **Without them the Worker still serves its pages.** The OAuth routes answer "not configured" (`503`).

## First-time setup

1. **Create a Cloudflare account** (free) at https://dash.cloudflare.com/sign-up and verify your email.
2. **Choose a `workers.dev` subdomain.** In the dashboard, open **Workers & Pages**. The first time, Cloudflare asks for a subdomain. It is public and part of every Worker's address: `https://habit-tracker.<subdomain>.workers.dev`.
3. **Sign Wrangler in.** It opens the browser for you to approve access:

   ```powershell
   npx wrangler login
   npx wrangler whoami
   ```

   Wrangler keeps its sign-in in your user profile, not in this repository.

## Deploy

```powershell
npm run deploy
```

- **What `deploy` checks first** (`predeploy`): every page value in `src/pages.ts` must be filled in, and the tests must pass. Then it runs `wrangler deploy`.
- **What a successful deploy shows:** the Worker's address.
- **Quick check:** open `https://habit-tracker.<subdomain>.workers.dev/health`, which should show `{"status":"ok"}`. Then open `/`, `/privacy`, `/terms` and `/support`.

## Set the secrets

**State-signing key** (any time after the first deploy). This generates 32 random bytes and sends them straight to Cloudflare without showing them:

```powershell
$bytes = New-Object byte[] 32
[System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
[Convert]::ToBase64String($bytes).TrimEnd('=').Replace('+', '-').Replace('/', '_') | npx wrangler secret put STATE_SIGNING_KEY
Remove-Variable bytes
```

**Notion client secret** (after creating the public connection, see `docs/notion-integration.md`). Run the command, then paste the secret at the prompt:

```powershell
npx wrangler secret put NOTION_CLIENT_SECRET
```

**Client ID.** Put it in `wrangler.toml` under `[vars]` as `NOTION_CLIENT_ID = "…"`, then run `npm run deploy` again.

`npx wrangler secret list` shows which secrets are set, never their values.

## Rotate a secret

- **`STATE_SIGNING_KEY`:** run the command above again. Sign-ins that are in progress at that moment fail with "This sign-in link isn't valid", and the user just clicks Connect again. Tokens that are already stored are unaffected.
- **`NOTION_CLIENT_SECRET`:**
  1. Regenerate it in Notion's developer portal.
  2. Run `npx wrangler secret put NOTION_CLIENT_SECRET` straight away.
  3. Until the new secret is set, sign-in, refresh and revoke fail.

## Local development

```powershell
Copy-Item .dev.vars.example .dev.vars   # fake, development-only values; git ignores .dev.vars
npm run dev                             # http://127.0.0.1:8787
```

With the fake values, the pages and `/start` work locally. `/callback` and `/refresh` need a real or fake Notion: the app's end-to-end tests run `wrangler dev` with `NOTION_API_BASE` pointing at a fake.

## Logs

- **What's logged:** one line per request, with the route, method, status, duration and a short reason such as `access_denied`. Never a URL with parameters, a body or a header.
- **Invocation logs are off:** Cloudflare's automatic invocation logs (`[observability.logs] invocation_logs = false`) would record the full `/callback` URL, including Notion's code.
- **Watching live:** `npx wrangler tail`.

## Tests

```powershell
npm test            # Vitest inside the Workers runtime (@cloudflare/vitest-plugin)
npm run typecheck
npm run lint
npm run types       # wrangler.toml and worker-configuration.d.ts agree
```
