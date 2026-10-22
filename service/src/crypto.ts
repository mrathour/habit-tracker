/**
 * The Worker side of the hand-off protocol (docs/handoff-protocol.md): signed state, and the
 * envelope that carries the sign-in result to the app. WebCrypto only; nothing is stored.
 */

export const PROTOCOL_VERSION = 1;
export const ENVELOPE_VERSION_BYTE = 0x01;
export const STATE_TTL_SECONDS = 600;
export const HANDOFF_TTL_SECONDS = 120;
const HKDF_INFO = new TextEncoder().encode("habit-tracker handoff v1");
const KEY_BYTES = 32;
const NONCE_BYTES = 12;

// --- base64url --------------------------------------------------------------------------

const B64URL = /^[A-Za-z0-9_-]*$/;

export function b64urlEncode(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** Strict base64url without padding. Throws on anything else. */
export function b64urlDecode(text: string): Uint8Array<ArrayBuffer> {
  if (!B64URL.test(text) || text.length % 4 === 1) throw new Error("not base64url");
  const binary = atob(text.replace(/-/g, "+").replace(/_/g, "/"));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

function concat(...parts: Uint8Array[]): Uint8Array<ArrayBuffer> {
  const out = new Uint8Array(parts.reduce((total, part) => total + part.length, 0));
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.length;
  }
  return out;
}

const ascii = (text: string) => new TextEncoder().encode(text);

// --- State ------------------------------------------------------------------------------

export interface StateClaims {
  /** Protocol version. */
  v: number;
  /** 32 random bytes, base64url. */
  n: string;
  /** Loopback port of the app's listener. */
  p: number;
  /** The app's X25519 public key, base64url. */
  k: string;
  /** Expiry, Unix seconds. */
  e: number;
}

async function hmacKey(signingKey: string): Promise<CryptoKey> {
  const raw = b64urlDecode(signingKey);
  if (raw.length < 32) throw new Error("STATE_SIGNING_KEY must be at least 32 bytes");
  return crypto.subtle.importKey("raw", raw, { name: "HMAC", hash: "SHA-256" }, false, [
    "sign",
    "verify",
  ]);
}

export async function signState(
  signingKey: string,
  port: number,
  publicKey: string,
  now: number,
): Promise<string> {
  const claims: StateClaims = {
    v: PROTOCOL_VERSION,
    n: b64urlEncode(crypto.getRandomValues(new Uint8Array(32))),
    p: port,
    k: publicKey,
    e: now + STATE_TTL_SECONDS,
  };
  const encoded = b64urlEncode(ascii(JSON.stringify(claims)));
  const signature = await crypto.subtle.sign("HMAC", await hmacKey(signingKey), ascii(encoded));
  return `${encoded}.${b64urlEncode(new Uint8Array(signature))}`;
}

export type StateCheck =
  | { ok: true; claims: StateClaims }
  | { ok: false; reason: "malformed" | "bad_signature" | "expired" };

/** Verify a state from /callback. The HMAC check is constant-time (`crypto.subtle.verify`). */
export async function verifyState(
  signingKey: string,
  state: string,
  now: number,
): Promise<StateCheck> {
  const parts = state.split(".");
  if (parts.length !== 2) return { ok: false, reason: "malformed" };
  const [encoded, signature] = parts as [string, string];
  let signatureBytes: Uint8Array<ArrayBuffer>;
  try {
    signatureBytes = b64urlDecode(signature);
  } catch {
    return { ok: false, reason: "malformed" };
  }
  const valid = await crypto.subtle.verify(
    "HMAC",
    await hmacKey(signingKey),
    signatureBytes,
    ascii(encoded),
  );
  if (!valid) return { ok: false, reason: "bad_signature" };

  let claims: unknown;
  try {
    claims = JSON.parse(new TextDecoder().decode(b64urlDecode(encoded)));
  } catch {
    return { ok: false, reason: "malformed" };
  }
  if (!isClaims(claims)) return { ok: false, reason: "malformed" };
  if (claims.e <= now) return { ok: false, reason: "expired" };
  return { ok: true, claims };
}

function isClaims(value: unknown): value is StateClaims {
  if (typeof value !== "object" || value === null) return false;
  const c = value as Record<string, unknown>;
  return (
    c["v"] === PROTOCOL_VERSION &&
    typeof c["n"] === "string" &&
    isPort(c["p"]) &&
    typeof c["k"] === "string" &&
    isPublicKey(c["k"]) &&
    typeof c["e"] === "number" &&
    Number.isInteger(c["e"])
  );
}

export function isPort(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value >= 1024 && value <= 65535;
}

export function isPublicKey(value: unknown): value is string {
  if (typeof value !== "string") return false;
  try {
    return b64urlDecode(value).length === KEY_BYTES;
  } catch {
    return false;
  }
}

// --- Envelope ---------------------------------------------------------------------------

export type ErrorCode =
  "access_denied" | "notion_error" | "notion_unreachable" | "server_misconfigured";

export interface HandoffToken {
  access_token: string;
  refresh_token: string;
  bot_id: string;
  workspace_id: string;
  workspace_name: string | null;
  workspace_icon: string | null;
}

export type HandoffResult =
  { result: "ok"; token: HandoffToken } | { result: "error"; error: ErrorCode };

/** Test hooks: a fixed ephemeral key and nonce reproduce the shared vectors byte for byte. */
export interface SealOptions {
  ephemeral?: CryptoKeyPair;
  nonce?: Uint8Array<ArrayBuffer>;
}

export function handoffPlaintext(result: HandoffResult, now: number): string {
  return JSON.stringify({ v: PROTOCOL_VERSION, exp: now + HANDOFF_TTL_SECONDS, ...result });
}

/** The raw 32-byte form of an X25519 public key. */
export async function exportRawKey(key: CryptoKey): Promise<Uint8Array<ArrayBuffer>> {
  const exported = await crypto.subtle.exportKey("raw", key);
  if (!(exported instanceof ArrayBuffer)) throw new Error("expected a raw key");
  return new Uint8Array(exported);
}

async function generateEphemeral(): Promise<CryptoKeyPair> {
  return (await crypto.subtle.generateKey({ name: "X25519" }, true, [
    "deriveBits",
  ])) as CryptoKeyPair;
}

export async function deriveKey(
  privateKey: CryptoKey,
  peerPublic: Uint8Array<ArrayBuffer>,
  salt: Uint8Array<ArrayBuffer>,
  usage: "encrypt" | "decrypt",
): Promise<CryptoKey> {
  const peer = await crypto.subtle.importKey("raw", peerPublic, { name: "X25519" }, false, []);
  // WebCrypto's field is `public`; @cloudflare/workers-types spells it `$public` (a reserved-word
  // workaround in their generator), so the object is typed by hand.
  const algorithm = { name: "X25519", public: peer } as unknown as SubtleCryptoDeriveKeyAlgorithm;
  const shared = new Uint8Array(await crypto.subtle.deriveBits(algorithm, privateKey, 256));
  if (shared.every((byte) => byte === 0)) throw new Error("low-order public key");
  const ikm = await crypto.subtle.importKey("raw", shared, "HKDF", false, ["deriveKey"]);
  return crypto.subtle.deriveKey(
    { name: "HKDF", hash: "SHA-256", salt, info: HKDF_INFO },
    ikm,
    { name: "AES-GCM", length: 256 },
    false,
    [usage],
  );
}

/** Encrypt `plaintext` to the app's public key, bound to `state` (docs/handoff-protocol.md §3). */
export async function seal(
  appPublicKey: string,
  state: string,
  plaintext: string,
  options: SealOptions = {},
): Promise<string> {
  const appPublic = b64urlDecode(appPublicKey);
  if (appPublic.length !== KEY_BYTES) throw new Error("app public key must be 32 bytes");
  const ephemeral = options.ephemeral ?? (await generateEphemeral());
  const ephemeralPublic = await exportRawKey(ephemeral.publicKey);
  const nonce = options.nonce ?? crypto.getRandomValues(new Uint8Array(NONCE_BYTES));
  const key = await deriveKey(
    ephemeral.privateKey,
    appPublic,
    concat(ephemeralPublic, appPublic),
    "encrypt",
  );
  const ciphertext = new Uint8Array(
    await crypto.subtle.encrypt(
      { name: "AES-GCM", iv: nonce, additionalData: ascii(state) },
      key,
      new TextEncoder().encode(plaintext),
    ),
  );
  return b64urlEncode(
    concat(new Uint8Array([ENVELOPE_VERSION_BYTE]), ephemeralPublic, nonce, ciphertext),
  );
}
