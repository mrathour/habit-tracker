import { env as testEnv } from "cloudflare:workers";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { b64urlEncode, STATE_TTL_SECONDS } from "../src/crypto.ts";
import { createHandler } from "../src/index.ts";
import { newAppPair, open } from "./helpers.ts";

const ORIGIN = "https://habit-tracker.example.workers.dev";
const CLIENT_ID = "client-id-123";
const CLIENT_SECRET = "client-secret-value-xyz";
const SIGNING_KEY = b64urlEncode(new Uint8Array(32).fill(3));
const NOW = 1_800_000_000;

const ACCESS_TOKEN = "ntn_access_token_value_0123456789";
const REFRESH_TOKEN = "nrt_refresh_token_value_0123456789";
const CODE = "one-time-code-abcdef";

/** Every value that must never appear in a log line. */
const SECRET_VALUES = [CLIENT_SECRET, SIGNING_KEY, ACCESS_TOKEN, REFRESH_TOKEN, CODE];

const TOKEN_RESPONSE = {
  access_token: ACCESS_TOKEN,
  refresh_token: REFRESH_TOKEN,
  token_type: "bearer",
  bot_id: "bot-1",
  workspace_id: "ws-1",
  workspace_name: "My Workspace",
  workspace_icon: "https://example.test/icon.png",
  owner: { type: "user", user: { id: "user-1", name: "Someone" } },
  duplicated_template_id: null,
};

interface NotionCall {
  url: string;
  authorization: string | null;
  body: Record<string, unknown>;
}

type NotionReply = Response | Error;

class FakeNotion {
  calls: NotionCall[] = [];
  replies: NotionReply[] = [];

  reply(...replies: NotionReply[]): this {
    this.replies.push(...replies);
    return this;
  }

  fetch = async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = input instanceof Request ? input.url : String(input);
    const headers = new Headers(init?.headers);
    this.calls.push({
      url,
      authorization: headers.get("Authorization"),
      body: JSON.parse(typeof init?.body === "string" ? init.body : "{}") as Record<
        string,
        unknown
      >,
    });
    const next = this.replies.shift() ?? new Error("no reply configured");
    if (next instanceof Error) throw next;
    return Promise.resolve(next);
  };
}

function notionJson(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const allowAll = { limit: () => Promise.resolve({ success: true }) } as unknown as RateLimit;

function makeEnv(overrides: Partial<Env> = {}): Env {
  return {
    ...testEnv,
    NOTION_CLIENT_ID: CLIENT_ID,
    NOTION_CLIENT_SECRET: CLIENT_SECRET,
    STATE_SIGNING_KEY: SIGNING_KEY,
    NOTION_API_BASE: "https://api.notion.com",
    OAUTH_LIMITER: allowAll,
    PAGE_LIMITER: allowAll,
    ...overrides,
  };
}

let notion: FakeNotion;
let clock: number;
let logs: string[];
let handle: ReturnType<typeof createHandler>;

beforeEach(() => {
  notion = new FakeNotion();
  clock = NOW;
  logs = [];
  vi.spyOn(console, "log").mockImplementation((line: unknown) => {
    logs.push(String(line));
  });
  handle = createHandler({ fetch: notion.fetch, now: () => clock });
});

afterEach(() => {
  // No log line may ever contain a secret, a token or a code.
  for (const line of logs) {
    for (const secret of SECRET_VALUES) expect(line).not.toContain(secret);
    expect(line).not.toContain("?");
  }
  vi.restoreAllMocks();
});

function post(path: string, body: unknown, headers: Record<string, string> = {}): Request {
  return new Request(`${ORIGIN}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...headers },
    body: typeof body === "string" ? body : JSON.stringify(body),
  });
}

async function startSignIn(env = makeEnv()) {
  const app = await newAppPair();
  const response = await handle(post("/start", { port: 52731, public_key: app.publicKey }), env);
  expect(response.status).toBe(200);
  const body = await response.json<{ state: string; authorize_url: string; server_time: number }>();
  return { app, ...body };
}

function callbackRequest(params: Record<string, string>, method = "GET"): Request {
  return new Request(`${ORIGIN}/callback?${new URLSearchParams(params).toString()}`, { method });
}

async function handoffFrom(
  response: Response,
  state: string,
  app: Awaited<ReturnType<typeof newAppPair>>,
) {
  expect(response.status).toBe(302);
  const location = new URL(response.headers.get("Location") ?? "");
  expect(location.protocol).toBe("http:");
  expect(location.hostname).toBe("127.0.0.1");
  expect(location.port).toBe("52731");
  expect(location.pathname).toBe("/done");
  expect(location.searchParams.get("state")).toBe(state);
  const payload = location.searchParams.get("payload") ?? "";
  // Only ciphertext travels through the browser.
  for (const secret of [ACCESS_TOKEN, REFRESH_TOKEN, CODE]) {
    expect(location.toString()).not.toContain(secret);
  }
  return JSON.parse(await open(app.pair, payload, state)) as Record<string, unknown>;
}

// --- /start --------------------------------------------------------------------------------

describe("POST /start", () => {
  it("returns a signed state, Notion's authorize URL and the server time", async () => {
    const { state, authorize_url: authorizeUrl, server_time: serverTime } = await startSignIn();
    expect(serverTime).toBe(NOW);
    expect(state.split(".")).toHaveLength(2);
    const url = new URL(authorizeUrl);
    expect(`${url.origin}${url.pathname}`).toBe("https://api.notion.com/v1/oauth/authorize");
    expect(Object.fromEntries(url.searchParams)).toEqual({
      client_id: CLIENT_ID,
      response_type: "code",
      owner: "user",
      redirect_uri: `${ORIGIN}/callback`,
      state,
    });
  });

  it.each([
    [{ port: 80, public_key: b64urlEncode(new Uint8Array(32)) }, "port"],
    [{ port: 70000, public_key: b64urlEncode(new Uint8Array(32)) }, "port"],
    [{ port: "52731", public_key: b64urlEncode(new Uint8Array(32)) }, "port"],
    [{ port: 52731.5, public_key: b64urlEncode(new Uint8Array(32)) }, "port"],
    [{ port: 52731, public_key: b64urlEncode(new Uint8Array(31)) }, "public_key"],
    [{ port: 52731, public_key: "not+base64" }, "public_key"],
    [{ port: 52731 }, "public_key"],
  ])("rejects %j", async (body, field) => {
    const response = await handle(post("/start", body), makeEnv());
    expect(response.status).toBe(400);
    const json = await response.json<{ error: string; message: string }>();
    expect(json.error).toBe("invalid_request");
    expect(json.message).toContain(field);
  });

  it.each([
    ["not JSON", "{oops"],
    ["an array", "[1, 2]"],
    ["null", "null"],
  ])("rejects a body that is %s", async (_label, body) => {
    expect((await handle(post("/start", body), makeEnv())).status).toBe(400);
  });

  it("rejects requests that aren't JSON", async () => {
    const request = post("/start", "port=1", {
      "Content-Type": "application/x-www-form-urlencoded",
    });
    expect((await handle(request, makeEnv())).status).toBe(415);
  });

  it("refuses browser requests", async () => {
    const request = post("/start", { port: 52731 }, { Origin: "https://evil.example" });
    const response = await handle(request, makeEnv());
    expect(response.status).toBe(403);
    expect(await response.json()).toMatchObject({ error: "browser_request" });
  });

  it("refuses large bodies", async () => {
    const response = await handle(post("/start", { pad: "x".repeat(5000) }), makeEnv());
    expect(response.status).toBe(413);
  });

  it("only accepts POST", async () => {
    expect((await handle(new Request(`${ORIGIN}/start`), makeEnv())).status).toBe(405);
  });

  it.each(["NOTION_CLIENT_SECRET", "STATE_SIGNING_KEY"] as const)(
    "says it isn't configured without %s",
    async (name) => {
      const app = await newAppPair();
      const request = post("/start", { port: 52731, public_key: app.publicKey });
      const response = await handle(request, makeEnv({ [name]: "" }));
      expect(response.status).toBe(503);
      expect(await response.json()).toMatchObject({ error: "server_misconfigured" });
    },
  );

  it("says it isn't configured without a client ID", async () => {
    const env = makeEnv({ NOTION_CLIENT_ID: "" });
    const app = await newAppPair();
    const response = await handle(post("/start", { port: 52731, public_key: app.publicKey }), env);
    expect(response.status).toBe(503);
  });
});

// --- /callback -----------------------------------------------------------------------------

describe("GET /callback", () => {
  it("exchanges the code and hands the encrypted tokens to the app", async () => {
    const { app, state } = await startSignIn();
    notion.reply(notionJson(TOKEN_RESPONSE));
    clock += 30;
    const response = await handle(callbackRequest({ code: CODE, state }), makeEnv());
    const result = await handoffFrom(response, state, app);
    expect(result).toEqual({
      v: 1,
      exp: NOW + 30 + 120,
      result: "ok",
      token: {
        access_token: ACCESS_TOKEN,
        refresh_token: REFRESH_TOKEN,
        bot_id: "bot-1",
        workspace_id: "ws-1",
        workspace_name: "My Workspace",
        workspace_icon: "https://example.test/icon.png",
      },
    });
    // User information and template IDs are not passed on.
    expect(JSON.stringify(result)).not.toContain("user-1");

    expect(notion.calls).toHaveLength(1);
    const call = notion.calls[0];
    expect(call?.url).toBe("https://api.notion.com/v1/oauth/token");
    expect(call?.authorization).toBe(`Basic ${btoa(`${CLIENT_ID}:${CLIENT_SECRET}`)}`);
    expect(call?.body).toEqual({
      grant_type: "authorization_code",
      code: CODE,
      redirect_uri: `${ORIGIN}/callback`,
    });
    expect(response.headers.get("Cache-Control")).toBe("no-store");
    expect(response.headers.get("Referrer-Policy")).toBe("no-referrer");
  });

  it("passes on null workspace details", async () => {
    const { app, state } = await startSignIn();
    notion.reply(notionJson({ ...TOKEN_RESPONSE, workspace_name: null, workspace_icon: null }));
    const result = await handoffFrom(
      await handle(callbackRequest({ code: CODE, state }), makeEnv()),
      state,
      app,
    );
    expect(result["token"]).toMatchObject({ workspace_name: null, workspace_icon: null });
  });

  it("tells the app when the user cancels, without calling Notion", async () => {
    const { app, state } = await startSignIn();
    const response = await handle(callbackRequest({ error: "access_denied", state }), makeEnv());
    expect(await handoffFrom(response, state, app)).toMatchObject({
      result: "error",
      error: "access_denied",
    });
    expect(notion.calls).toHaveLength(0);
    expect(logs.at(-1)).toContain('"reason":"access_denied"');
  });

  it("reports other Notion redirect errors as notion_error", async () => {
    const { app, state } = await startSignIn();
    const response = await handle(callbackRequest({ error: "server_error", state }), makeEnv());
    expect(await handoffFrom(response, state, app)).toMatchObject({ error: "notion_error" });
  });

  it("reports a missing code as notion_error", async () => {
    const { app, state } = await startSignIn();
    const response = await handle(callbackRequest({ state }), makeEnv());
    expect(await handoffFrom(response, state, app)).toMatchObject({ error: "notion_error" });
    expect(notion.calls).toHaveLength(0);
  });

  it.each([
    ["Notion rejects the code", () => notionJson({ error: "invalid_grant" }, 400), "notion_error"],
    ["Notion has a server error", () => notionJson({}, 502), "notion_unreachable"],
    ["Notion can't be reached", () => new Error("connection reset"), "notion_unreachable"],
    ["Notion's response lacks tokens", () => notionJson({ bot_id: "b" }), "notion_error"],
    ["Notion's response isn't JSON", () => new Response("<html>", { status: 200 }), "notion_error"],
  ])("tells the app when %s", async (_label, reply, error) => {
    const { app, state } = await startSignIn();
    notion.reply(reply());
    const response = await handle(callbackRequest({ code: CODE, state }), makeEnv());
    expect(await handoffFrom(response, state, app)).toMatchObject({ result: "error", error });
  });

  it("times out a slow Notion", async () => {
    const { app, state } = await startSignIn();
    let signal: AbortSignal | undefined;
    const slow = createHandler({
      fetch: (_input, init) => {
        signal = init?.signal ?? undefined;
        return Promise.reject(new DOMException("The operation timed out.", "TimeoutError"));
      },
      now: () => clock,
    });
    const response = await slow(callbackRequest({ code: CODE, state }), makeEnv());
    expect(signal).toBeDefined();
    expect(await handoffFrom(response, state, app)).toMatchObject({ error: "notion_unreachable" });
  });

  it("rejects an expired state with a page, not a redirect", async () => {
    const { state } = await startSignIn();
    clock += STATE_TTL_SECONDS;
    const response = await handle(callbackRequest({ code: CODE, state }), makeEnv());
    expect(response.status).toBe(400);
    expect(response.headers.get("Location")).toBeNull();
    expect(response.headers.get("Content-Type")).toBe("text/html; charset=utf-8");
    expect(await response.text()).toContain("This sign-in link has expired");
    expect(notion.calls).toHaveLength(0);
  });

  it.each([
    ["missing", ""],
    ["garbage", "garbage"],
    ["three parts", "a.b.c"],
  ])("rejects a %s state", async (_label, state) => {
    const response = await handle(callbackRequest({ code: CODE, state }), makeEnv());
    expect(response.status).toBe(400);
    expect(await response.text()).toContain("This sign-in link isn't valid");
    expect(notion.calls).toHaveLength(0);
  });

  it("rejects a state signed with another key", async () => {
    const { state } = await startSignIn(
      makeEnv({ STATE_SIGNING_KEY: b64urlEncode(new Uint8Array(32).fill(9)) }),
    );
    const response = await handle(callbackRequest({ code: CODE, state }), makeEnv());
    expect(response.status).toBe(400);
    expect(logs.at(-1)).toContain('"reason":"state_bad_signature"');
  });

  it("can't be redirected elsewhere by editing the state", async () => {
    const { state } = await startSignIn();
    const [encoded, signature] = state.split(".") as [string, string];
    const claims = JSON.parse(atob(encoded.replace(/-/g, "+").replace(/_/g, "/"))) as Record<
      string,
      unknown
    >;
    claims["p"] = 8080;
    const forged = `${b64urlEncode(new TextEncoder().encode(JSON.stringify(claims)))}.${signature}`;
    const response = await handle(callbackRequest({ code: CODE, state: forged }), makeEnv());
    expect(response.status).toBe(400);
    expect(response.headers.get("Location")).toBeNull();
  });

  it("explains in the browser when it isn't configured", async () => {
    const { state } = await startSignIn();
    const response = await handle(
      callbackRequest({ code: CODE, state }),
      makeEnv({ STATE_SIGNING_KEY: "" }),
    );
    expect(response.status).toBe(503);
    expect(await response.text()).toContain("Sign-in isn't available right now");
  });

  it("error pages never echo request data", async () => {
    const response = await handle(
      callbackRequest({ code: "<script>x</script>", state: "<b>" }),
      makeEnv(),
    );
    const html = await response.text();
    expect(html).not.toContain("<script>");
    expect(html).not.toContain("<b>");
  });

  it("only accepts GET", async () => {
    const response = await handle(callbackRequest({ state: "x" }, "POST"), makeEnv());
    expect(response.status).toBe(405);
  });

  it("produces a different envelope each time, even for the same state", async () => {
    const { app, state } = await startSignIn();
    const first = await handle(callbackRequest({ error: "access_denied", state }), makeEnv());
    const second = await handle(callbackRequest({ error: "access_denied", state }), makeEnv());
    expect(first.headers.get("Location")).not.toBe(second.headers.get("Location"));
    // The Worker is stateless; replay protection is the app's one-time key (tests/test_handoff.py).
    await handoffFrom(first, state, app);
  });
});

// --- /refresh ------------------------------------------------------------------------------

describe("POST /refresh", () => {
  it("returns the new token pair", async () => {
    notion.reply(
      notionJson({ ...TOKEN_RESPONSE, refresh_token: "nrt_new_refresh_token_9876543210" }),
    );
    const response = await handle(post("/refresh", { refresh_token: REFRESH_TOKEN }), makeEnv());
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      access_token: ACCESS_TOKEN,
      refresh_token: "nrt_new_refresh_token_9876543210",
      bot_id: "bot-1",
      workspace_id: "ws-1",
      workspace_name: "My Workspace",
      workspace_icon: "https://example.test/icon.png",
    });
    expect(notion.calls[0]?.body).toEqual({
      grant_type: "refresh_token",
      refresh_token: REFRESH_TOKEN,
    });
    expect(notion.calls[0]?.authorization).toBe(`Basic ${btoa(`${CLIENT_ID}:${CLIENT_SECRET}`)}`);
    expect(response.headers.get("Cache-Control")).toBe("no-store");
  });

  it.each([
    [
      "Notion says invalid_grant",
      () => notionJson({ error: "invalid_grant" }, 400),
      400,
      "invalid_grant",
    ],
    [
      "Notion's code field says invalid_grant",
      () => notionJson({ code: "invalid_grant" }, 400),
      400,
      "invalid_grant",
    ],
    [
      "Notion rejects the client",
      () => notionJson({ error: "invalid_client" }, 401),
      502,
      "notion_error",
    ],
    ["Notion has a server error", () => notionJson({}, 503), 503, "notion_unreachable"],
    ["Notion can't be reached", () => new Error("offline"), 503, "notion_unreachable"],
    ["Notion's response lacks tokens", () => notionJson({}), 502, "notion_bad_response"],
  ])("maps the case where %s", async (_label, reply, status, error) => {
    notion.reply(reply());
    const response = await handle(post("/refresh", { refresh_token: REFRESH_TOKEN }), makeEnv());
    expect(response.status).toBe(status);
    expect(await response.json()).toMatchObject({ error });
  });

  it.each([{}, { refresh_token: "" }, { refresh_token: 42 }])("rejects %j", async (body) => {
    expect((await handle(post("/refresh", body), makeEnv())).status).toBe(400);
    expect(notion.calls).toHaveLength(0);
  });

  it("refuses browser requests", async () => {
    const request = post(
      "/refresh",
      { refresh_token: REFRESH_TOKEN },
      { Origin: "https://evil.example" },
    );
    expect((await handle(request, makeEnv())).status).toBe(403);
    expect(notion.calls).toHaveLength(0);
  });

  it("says it isn't configured without the client secret", async () => {
    const response = await handle(
      post("/refresh", { refresh_token: REFRESH_TOKEN }),
      makeEnv({ NOTION_CLIENT_SECRET: "" }),
    );
    expect(response.status).toBe(503);
  });
});

// --- /revoke -------------------------------------------------------------------------------

describe("POST /revoke", () => {
  it("revokes the token with Notion", async () => {
    notion.reply(notionJson({}));
    const response = await handle(post("/revoke", { token: ACCESS_TOKEN }), makeEnv());
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ revoked: true });
    expect(notion.calls[0]?.url).toBe("https://api.notion.com/v1/oauth/revoke");
    expect(notion.calls[0]?.body).toEqual({ token: ACCESS_TOKEN });
  });

  it.each([
    ["Notion rejects it", () => notionJson({ error: "invalid_request" }, 400), 502],
    ["Notion is down", () => notionJson({}, 500), 503],
    ["Notion can't be reached", () => new Error("offline"), 503],
  ])("reports when %s", async (_label, reply, status) => {
    notion.reply(reply());
    expect((await handle(post("/revoke", { token: ACCESS_TOKEN }), makeEnv())).status).toBe(status);
  });

  it("requires a token", async () => {
    expect((await handle(post("/revoke", {}), makeEnv())).status).toBe(400);
  });
});

// --- Rate limiting -------------------------------------------------------------------------

describe("rate limiting", () => {
  it("limits OAuth routes per IP address", async () => {
    let calls = 0;
    const limiter = {
      limit: ({ key }: { key: string }) => {
        calls++;
        expect(key).toBe("203.0.113.9");
        return Promise.resolve({ success: calls <= 2 });
      },
    };
    const env = makeEnv({ OAUTH_LIMITER: limiter });
    const request = () => post("/revoke", {}, { "CF-Connecting-IP": "203.0.113.9" });
    expect((await handle(request(), env)).status).toBe(400);
    expect((await handle(request(), env)).status).toBe(400);
    const limited = await handle(request(), env);
    expect(limited.status).toBe(429);
    expect(await limited.json()).toMatchObject({ error: "rate_limited" });
  });

  it("uses the real binding with the configured limit", async () => {
    // wrangler.toml: OAUTH_LIMITER allows 20 requests a minute per key.
    const env = { ...makeEnv(), OAUTH_LIMITER: testEnv.OAUTH_LIMITER };
    const statuses: number[] = [];
    for (let i = 0; i < 25; i++) {
      const response = await handle(
        post("/revoke", {}, { "CF-Connecting-IP": "198.51.100.7" }),
        env,
      );
      statuses.push(response.status);
    }
    expect(statuses.slice(0, 20).every((status) => status === 400)).toBe(true);
    expect(statuses.at(-1)).toBe(429);
  });

  it("limits pages separately and more loosely", async () => {
    const blocked = { limit: () => Promise.resolve({ success: false }) } as unknown as RateLimit;
    const env = makeEnv({ PAGE_LIMITER: blocked });
    expect((await handle(new Request(`${ORIGIN}/privacy`), env)).status).toBe(429);
    const app = await newAppPair();
    expect(
      (await handle(post("/start", { port: 52731, public_key: app.publicKey }), env)).status,
    ).toBe(200);
  });
});
