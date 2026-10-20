# Notion public connection: "Habit Tracker"

How the public connection behind "Connect to Notion" is set up (`PLAN.md` 12.1). It is separate from the WebNotes extension's connection.

## Values for the developer portal

| Field | Value |
|---|---|
| Connection name | `Habit Tracker` |
| Development workspace | Your own workspace (the one with Work Log) |
| Installation scope | **Any workspace**. This can't be changed later, and "Selected workspaces only" would block other users and any future Marketplace listing. |
| Capabilities | **Read content** only. Leave *Update content*, *Insert content* and every comment capability off. User information: **No user information**. |
| Redirect URI | `https://habit-tracker.mrathour.workers.dev/callback` (exactly; Notion matches it character for character) |
| Website / homepage | `https://habit-tracker.mrathour.workers.dev/` |
| Privacy policy URL | `https://habit-tracker.mrathour.workers.dev/privacy` |
| Terms of use URL | `https://habit-tracker.mrathour.workers.dev/terms` |
| Support URL | `https://habit-tracker.mrathour.workers.dev/support` |
| Support / contact email | `mrathour1997@gmail.com` |
| Developer or company name | `Mayank Rathour` |
| Icon / logo | `service/pages/icon.png` (512 × 512 PNG), also at `https://habit-tracker.mrathour.workers.dev/icon.png` |
| Short description | Reads your Notion work log (read-only) and turns your work sessions into habit-tracking charts on your Windows PC. |

## Steps

1. Open Notion's developer portal at https://www.notion.so/developers and sign in.
2. In the sidebar, under **Build**, choose **Public connections**. Then click **Create new connection**.
3. Fill in the form with the values above. Double-check **Installation scope** and **Capabilities** before saving: scope can't be changed afterwards.
4. Create the connection, then open its **Configuration** tab. It shows:
   - **OAuth client ID:** public. Put it in `service/wrangler.toml` as `NOTION_CLIENT_ID` (or give it to Claude Code).
   - **OAuth client secret:** private. Set it only with `npx wrangler secret put NOTION_CLIENT_SECRET` in your own PowerShell window (see `docs/token-service.md`). Never paste it anywhere else.
5. Redeploy the token service (`npm run deploy` in `service/`).

## Review and the Marketplace

**Confirmed 2026-10-20, for the author's own workspace only: sign-in works without review.** A live test signed in through the deployed token service, decrypted the hand-off in the app's code, and revoked the token. The connection had not been submitted for review. Signing in from a workspace that doesn't own the connection is still unverified; that is Phase 3 check (d).

The redirect URI must match character for character. If it doesn't, Notion's consent page shows "Something went wrong: Missing or invalid redirect_uri".

- **Review and other workspaces.** Notion's docs say a public connection "can be used via its OAuth flow without being listed". Review is for listing on the Notion Marketplace, which is not part of v1.
- **The Authorization URL field.** The authorization guide says the field in the Configuration tab "populates after a public connection is submitted for review". The app doesn't need that field: the token service builds the same URL from the client ID.
- **If Notion refuses sign-in for an unreviewed connection,** submit it for review from the Listings section. Notion says it replies within 5–10 business days by email. The values in the table above are what the listing asks for.

Sources:
- [Public connections](https://developers.notion.com/guides/get-started/public-connections)
- [Authorization](https://developers.notion.com/guides/get-started/authorization)
- [List on the Marketplace](https://developers.notion.com/guides/get-started/marketplace-listing)
