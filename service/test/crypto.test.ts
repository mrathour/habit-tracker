import { describe, expect, it } from "vitest";

import {
  b64urlDecode,
  b64urlEncode,
  deriveKey,
  ENVELOPE_VERSION_BYTE,
  exportRawKey,
  handoffPlaintext,
  seal,
  signState,
  STATE_TTL_SECONDS,
  verifyState,
} from "../src/crypto.ts";
import vectors from "./fixtures/handoff-v1.json";

const SIGNING_KEY = b64urlEncode(new Uint8Array(32).fill(7));
const NOW = 1_800_000_000;

async function importPair(privateB64: string, publicB64: string): Promise<CryptoKeyPair> {
  const jwk = { kty: "OKP", crv: "X25519", d: privateB64, x: publicB64, ext: true };
  const privateKey = await crypto.subtle.importKey("jwk", jwk, { name: "X25519" }, true, [
    "deriveBits",
  ]);
  const publicKey = await crypto.subtle.importKey(
    "raw",
    b64urlDecode(publicB64),
    { name: "X25519" },
    true,
    [],
  );
  return { privateKey, publicKey };
}

/** Test-only decryption, mirroring app/notion/handoff.py. */
async function open(appPair: CryptoKeyPair, envelope: string, state: string): Promise<string> {
  const raw = b64urlDecode(envelope);
  expect(raw[0]).toBe(ENVELOPE_VERSION_BYTE);
  const ephemeralPublic = raw.slice(1, 33);
  const nonce = raw.slice(33, 45);
  const appPublic = await exportRawKey(appPair.publicKey);
  const salt = new Uint8Array([...ephemeralPublic, ...appPublic]);
  const key = await deriveKey(appPair.privateKey, ephemeralPublic, salt, "decrypt");
  const plaintext = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: nonce, additionalData: new TextEncoder().encode(state) },
    key,
    raw.slice(45),
  );
  return new TextDecoder().decode(plaintext);
}

async function newAppPair(): Promise<{ pair: CryptoKeyPair; publicKey: string }> {
  const pair = (await crypto.subtle.generateKey({ name: "X25519" }, true, [
    "deriveBits",
  ])) as CryptoKeyPair;
  const publicKey = b64urlEncode(await exportRawKey(pair.publicKey));
  return { pair, publicKey };
}

describe("shared vectors (docs/handoff-protocol.md)", () => {
  it.each(vectors.cases)("reproduces $name byte for byte", async (testCase) => {
    const ephemeral = await importPair(
      testCase.ephemeral_private_key,
      testCase.ephemeral_public_key,
    );
    const envelope = await seal(vectors.app_public_key, vectors.state, testCase.plaintext, {
      ephemeral,
      nonce: b64urlDecode(testCase.nonce),
    });
    expect(envelope).toBe(testCase.envelope);
  });

  it.each(vectors.cases)("the app key opens $name", async (testCase) => {
    const appPair = await importPair(vectors.app_private_key, vectors.app_public_key);
    expect(await open(appPair, testCase.envelope, vectors.state)).toBe(testCase.plaintext);
  });
});

describe("seal", () => {
  it("round-trips with a fresh key and binds the state", async () => {
    const app = await newAppPair();
    const plaintext = handoffPlaintext({ result: "error", error: "access_denied" }, NOW);
    const envelope = await seal(app.publicKey, "state-1", plaintext);
    expect(await open(app.pair, envelope, "state-1")).toBe(plaintext);
    await expect(open(app.pair, envelope, "state-2")).rejects.toThrow();
  });

  it("uses a new ephemeral key and nonce every time", async () => {
    const app = await newAppPair();
    const a = b64urlDecode(await seal(app.publicKey, "s", "{}"));
    const b = b64urlDecode(await seal(app.publicKey, "s", "{}"));
    expect(a.slice(1, 45)).not.toEqual(b.slice(1, 45));
  });

  it("rejects a public key of the wrong length", async () => {
    await expect(seal(b64urlEncode(new Uint8Array(31)), "s", "{}")).rejects.toThrow("32 bytes");
  });

  it("rejects a low-order public key", async () => {
    await expect(seal(b64urlEncode(new Uint8Array(32)), "s", "{}")).rejects.toThrow();
  });

  it("puts the 120-second expiry and version in the plaintext", () => {
    expect(JSON.parse(handoffPlaintext({ result: "error", error: "notion_error" }, NOW))).toEqual({
      v: 1,
      exp: NOW + 120,
      result: "error",
      error: "notion_error",
    });
  });
});

describe("state", () => {
  const PUBLIC_KEY = b64urlEncode(new Uint8Array(32).fill(9));

  it("verifies its own state and returns the claims", async () => {
    const state = await signState(SIGNING_KEY, 52731, PUBLIC_KEY, NOW);
    const check = await verifyState(SIGNING_KEY, state, NOW + 1);
    expect(check.ok).toBe(true);
    if (check.ok) {
      expect(check.claims).toMatchObject({
        v: 1,
        p: 52731,
        k: PUBLIC_KEY,
        e: NOW + STATE_TTL_SECONDS,
      });
      expect(b64urlDecode(check.claims.n)).toHaveLength(32);
    }
  });

  it("uses a fresh nonce for every state", async () => {
    const a = await signState(SIGNING_KEY, 52731, PUBLIC_KEY, NOW);
    const b = await signState(SIGNING_KEY, 52731, PUBLIC_KEY, NOW);
    expect(a).not.toBe(b);
  });

  it("expires after 10 minutes", async () => {
    const state = await signState(SIGNING_KEY, 52731, PUBLIC_KEY, NOW);
    expect(await verifyState(SIGNING_KEY, state, NOW + STATE_TTL_SECONDS)).toEqual({
      ok: false,
      reason: "expired",
    });
  });

  it("rejects a state signed with another key", async () => {
    const state = await signState(b64urlEncode(new Uint8Array(32).fill(1)), 52731, PUBLIC_KEY, NOW);
    expect(await verifyState(SIGNING_KEY, state, NOW)).toEqual({
      ok: false,
      reason: "bad_signature",
    });
  });

  it("rejects tampered claims", async () => {
    const state = await signState(SIGNING_KEY, 52731, PUBLIC_KEY, NOW);
    const [encoded, signature] = state.split(".") as [string, string];
    const claims = JSON.parse(new TextDecoder().decode(b64urlDecode(encoded))) as Record<
      string,
      unknown
    >;
    claims["p"] = 4444;
    const forged = `${b64urlEncode(new TextEncoder().encode(JSON.stringify(claims)))}.${signature}`;
    expect(await verifyState(SIGNING_KEY, forged, NOW)).toEqual({
      ok: false,
      reason: "bad_signature",
    });
  });

  it.each(["", "a", "a.b.c", "abc.%%%", "abc.def"])("rejects malformed state %j", async (state) => {
    const check = await verifyState(SIGNING_KEY, state, NOW);
    expect(check.ok).toBe(false);
  });

  it("rejects correctly signed but invalid claims", async () => {
    const encoded = b64urlEncode(new TextEncoder().encode(JSON.stringify({ v: 1, p: 80 })));
    const key = await crypto.subtle.importKey(
      "raw",
      b64urlDecode(SIGNING_KEY),
      { name: "HMAC", hash: "SHA-256" },
      false,
      ["sign"],
    );
    const signature = new Uint8Array(
      await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(encoded)),
    );
    expect(await verifyState(SIGNING_KEY, `${encoded}.${b64urlEncode(signature)}`, NOW)).toEqual({
      ok: false,
      reason: "malformed",
    });
  });

  it("refuses a signing key shorter than 32 bytes", async () => {
    await expect(
      signState(b64urlEncode(new Uint8Array(16)), 52731, PUBLIC_KEY, NOW),
    ).rejects.toThrow("32 bytes");
  });
});

describe("base64url", () => {
  it.each(["a+b", "a/b", "ab==", "a"])("rejects %j", (text) => {
    expect(() => b64urlDecode(text)).toThrow("not base64url");
  });

  it("round-trips every byte value", () => {
    const bytes = new Uint8Array(256).map((_, i) => i);
    expect(b64urlDecode(b64urlEncode(bytes))).toEqual(bytes);
  });
});
