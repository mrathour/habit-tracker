// Secrets set with `wrangler secret put` (docs/token-service.md). `wrangler types` only sees
// [vars], so these are declared here, merged into both Env declarations it generates. Both are
// optional at the type level: a Worker without them answers "not configured" instead of failing.
interface Env {
  NOTION_CLIENT_SECRET?: string;
  STATE_SIGNING_KEY?: string;
}
declare namespace Cloudflare {
  interface Env {
    NOTION_CLIENT_SECRET?: string;
    STATE_SIGNING_KEY?: string;
  }
}
