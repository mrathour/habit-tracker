/**
 * The OAuth routes (PLAN.md 12.2, docs/handoff-protocol.md):
 *
 * - `POST /start`: sign a state for the app's loopback port and one-time public key.
 * - `GET /callback`: Notion's redirect URI. Exchange the code, encrypt the result to the app's
 *   key, and redirect the browser to the app's loopback listener.
 * - `POST /refresh`: exchange a refresh token for a new token pair.
 * - `POST /revoke`: revoke a token.
 *
 * Nothing is stored. Tokens exist only in memory for one request and never reach a log.
 */

import {
  type ErrorCode,
  type HandoffResult,
  type HandoffToken,
  handoffPlaintext,
  isPort,
  isPublicKey,
  seal,
  signState,
  verifyState,
} from "./crypto.ts";
import { errorPage } from "./pages.ts";

/** Everything the routes need from the outside world, so tests can replace it. */
export interface Deps {
  fetch: typeof fetch;
  /** Unix seconds. */
  now: () => number;
}

export interface Outcome {
  response: Response;
  /** A short machine-readable reason for the log. Never user data. */
  reason?: string;
}

export const NOTION_TIMEOUT_MS = 10_000;
const MAX_BODY_BYTES = 4096;

interface Config {
  clientId: string;
  clientSecret: string;
  signingKey: string;
  apiBase: string;
}

function config(env: Env): Config | null {
  const clientId = env.NOTION_CLIENT_ID;
  const clientSecret = env.NOTION_CLIENT_SECRET ?? "";
  const signingKey = env.STATE_SIGNING_KEY ?? "";
  if (!clientId || !clientSecret || !signingKey) return null;
  return { clientId, clientSecret, signingKey, apiBase: env.NOTION_API_BASE.replace(/\/+$/, "") };
}

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

export function errorJson(status: number, error: string, message: string): Outcome {
  return { response: json({ error, message }, status), reason: error };
}

const NOT_CONFIGURED = (): Outcome =>
  errorJson(503, "server_misconfigured", "The sign-in service isn't set up yet.");

/**
 * The app calls the POST routes directly. A browser request (one with an Origin header) is
 * refused, so a web page can't drive these routes on someone's behalf.
 */
async function readJsonBody(request: Request): Promise<Record<string, unknown> | Outcome> {
  if (request.method !== "POST") return errorJson(405, "method_not_allowed", "Use POST.");
  if (request.headers.has("Origin")) {
    return errorJson(403, "browser_request", "This route is only for the Habit Tracker app.");
  }
  const type = request.headers.get("Content-Type") ?? "";
  if (!type.toLowerCase().startsWith("application/json")) {
    return errorJson(415, "unsupported_media_type", "Send JSON.");
  }
  const length = Number(request.headers.get("Content-Length") ?? "0");
  if (length > MAX_BODY_BYTES) return errorJson(413, "body_too_large", "The request is too large.");
  const text = await request.text();
  if (new TextEncoder().encode(text).length > MAX_BODY_BYTES) {
    return errorJson(413, "body_too_large", "The request is too large.");
  }
  try {
    const body: unknown = JSON.parse(text);
    if (typeof body === "object" && body !== null && !Array.isArray(body)) {
      return body as Record<string, unknown>;
    }
  } catch {
    // fall through
  }
  return errorJson(400, "invalid_request", "The request body must be a JSON object.");
}

function isOutcome(value: unknown): value is Outcome {
  return typeof value === "object" && value !== null && "response" in value;
}

// --- Notion's token endpoints ------------------------------------------------------------

type NotionCall =
  | { kind: "ok"; body: Record<string, unknown> }
  | { kind: "rejected"; status: number; error: string }
  | { kind: "unreachable" };

async function callNotion(
  deps: Deps,
  cfg: Config,
  path: "/v1/oauth/token" | "/v1/oauth/revoke",
  body: Record<string, string>,
): Promise<NotionCall> {
  let response: Response;
  try {
    response = await deps.fetch(`${cfg.apiBase}${path}`, {
      method: "POST",
      headers: {
        Authorization: `Basic ${btoa(`${cfg.clientId}:${cfg.clientSecret}`)}`,
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(NOTION_TIMEOUT_MS),
    });
  } catch {
    return { kind: "unreachable" };
  }
  if (response.status >= 500) return { kind: "unreachable" };
  const parsed: unknown = await response.json().catch(() => null);
  const data =
    typeof parsed === "object" && parsed !== null ? (parsed as Record<string, unknown>) : {};
  if (!response.ok) {
    // OAuth errors use `error`; Notion's API errors use `code`.
    const code = typeof data["error"] === "string" ? data["error"] : data["code"];
    return {
      kind: "rejected",
      status: response.status,
      error: typeof code === "string" ? code : "",
    };
  }
  return { kind: "ok", body: data };
}

function readToken(body: Record<string, unknown>): HandoffToken | null {
  const text = (name: string) => (typeof body[name] === "string" ? body[name] : null);
  const access = text("access_token");
  const refresh = text("refresh_token");
  const botId = text("bot_id");
  const workspaceId = text("workspace_id");
  if (!access || !refresh || !botId || !workspaceId) return null;
  // Notion's `owner` (user information) and `duplicated_template_id` are deliberately dropped.
  return {
    access_token: access,
    refresh_token: refresh,
    bot_id: botId,
    workspace_id: workspaceId,
    workspace_name: text("workspace_name"),
    workspace_icon: text("workspace_icon"),
  };
}

// --- Routes -------------------------------------------------------------------------------

export function redirectUri(request: Request): string {
  return `${new URL(request.url).origin}/callback`;
}

export async function start(request: Request, env: Env, deps: Deps): Promise<Outcome> {
  const body = await readJsonBody(request);
  if (isOutcome(body)) return body;
  const cfg = config(env);
  if (cfg === null) return NOT_CONFIGURED();
  if (!isPort(body["port"])) {
    return errorJson(400, "invalid_request", "port must be an integer from 1024 to 65535.");
  }
  if (!isPublicKey(body["public_key"])) {
    return errorJson(400, "invalid_request", "public_key must be a 32-byte X25519 key.");
  }
  const now = deps.now();
  const state = await signState(cfg.signingKey, body["port"], body["public_key"], now);
  const authorize = new URL(`${cfg.apiBase}/v1/oauth/authorize`);
  authorize.search = new URLSearchParams({
    client_id: cfg.clientId,
    response_type: "code",
    owner: "user",
    redirect_uri: redirectUri(request),
    state,
  }).toString();
  return { response: json({ state, authorize_url: authorize.toString(), server_time: now }) };
}

export async function callback(request: Request, env: Env, deps: Deps): Promise<Outcome> {
  if (request.method !== "GET") return errorJson(405, "method_not_allowed", "Use GET.");
  const params = new URL(request.url).searchParams;
  const state = params.get("state") ?? "";
  const cfg = config(env);
  if (cfg === null) {
    // Without the signing key the state can't be checked, so the app can't be told. Explain in
    // the browser instead.
    return {
      response: errorPage(
        503,
        "Sign-in isn't available right now",
        "Habit Tracker's sign-in service isn't set up yet. Return to Habit Tracker and try again later, or connect with a token in Settings → Advanced.",
      ),
      reason: "server_misconfigured",
    };
  }
  const now = deps.now();
  const check = await verifyState(cfg.signingKey, state, now);
  if (!check.ok) {
    return {
      response: errorPage(
        400,
        check.reason === "expired"
          ? "This sign-in link has expired"
          : "This sign-in link isn't valid",
        "Return to Habit Tracker and click Connect to Notion again.",
      ),
      reason: `state_${check.reason}`,
    };
  }

  let result: HandoffResult;
  let reason: string | undefined;
  const notionError = params.get("error");
  const code = params.get("code");
  if (notionError !== null) {
    const error: ErrorCode = notionError === "access_denied" ? "access_denied" : "notion_error";
    result = { result: "error", error };
    reason = error;
  } else if (!code) {
    result = { result: "error", error: "notion_error" };
    reason = "missing_code";
  } else {
    const exchange = await callNotion(deps, cfg, "/v1/oauth/token", {
      grant_type: "authorization_code",
      code,
      redirect_uri: redirectUri(request),
    });
    const token = exchange.kind === "ok" ? readToken(exchange.body) : null;
    if (token !== null) {
      result = { result: "ok", token };
    } else {
      const error: ErrorCode =
        exchange.kind === "unreachable" ? "notion_unreachable" : "notion_error";
      result = { result: "error", error };
      reason = exchange.kind === "ok" ? "notion_bad_response" : error;
    }
  }

  const payload = await seal(check.claims.k, state, handoffPlaintext(result, now));
  const target = new URL(`http://127.0.0.1:${check.claims.p}/done`);
  target.search = new URLSearchParams({ state, payload }).toString();
  return {
    response: new Response(null, { status: 302, headers: { Location: target.toString() } }),
    ...(reason === undefined ? {} : { reason }),
  };
}

function rejected(call: Extract<NotionCall, { kind: "rejected" | "unreachable" }>): Outcome {
  if (call.kind === "unreachable") {
    return errorJson(503, "notion_unreachable", "Notion couldn't be reached. Try again shortly.");
  }
  if (call.error === "invalid_grant") {
    return errorJson(400, "invalid_grant", "Notion no longer accepts this sign-in.");
  }
  return errorJson(502, "notion_error", "Notion rejected the request.");
}

export async function refresh(request: Request, env: Env, deps: Deps): Promise<Outcome> {
  const body = await readJsonBody(request);
  if (isOutcome(body)) return body;
  const cfg = config(env);
  if (cfg === null) return NOT_CONFIGURED();
  const refreshToken = body["refresh_token"];
  if (typeof refreshToken !== "string" || refreshToken.length === 0) {
    return errorJson(400, "invalid_request", "refresh_token is required.");
  }
  const call = await callNotion(deps, cfg, "/v1/oauth/token", {
    grant_type: "refresh_token",
    refresh_token: refreshToken,
  });
  if (call.kind !== "ok") return rejected(call);
  const token = readToken(call.body);
  if (token === null) {
    return errorJson(502, "notion_bad_response", "Notion's response was incomplete.");
  }
  return { response: json(token) };
}

export async function revoke(request: Request, env: Env, deps: Deps): Promise<Outcome> {
  const body = await readJsonBody(request);
  if (isOutcome(body)) return body;
  const cfg = config(env);
  if (cfg === null) return NOT_CONFIGURED();
  const token = body["token"];
  if (typeof token !== "string" || token.length === 0) {
    return errorJson(400, "invalid_request", "token is required.");
  }
  const call = await callNotion(deps, cfg, "/v1/oauth/revoke", { token });
  if (call.kind !== "ok") return rejected(call);
  return { response: json({ revoked: true }) };
}
