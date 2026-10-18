/** Test-only helpers that mirror the app's side of the hand-off (app/notion/handoff.py). */
import { expect } from "vitest";

import {
  b64urlDecode,
  b64urlEncode,
  deriveKey,
  ENVELOPE_VERSION_BYTE,
  exportRawKey,
} from "../src/crypto.ts";

export async function importPair(privateB64: string, publicB64: string): Promise<CryptoKeyPair> {
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
export async function open(
  appPair: CryptoKeyPair,
  envelope: string,
  state: string,
): Promise<string> {
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

export async function newAppPair(): Promise<{ pair: CryptoKeyPair; publicKey: string }> {
  const pair = (await crypto.subtle.generateKey({ name: "X25519" }, true, [
    "deriveBits",
  ])) as CryptoKeyPair;
  const publicKey = b64urlEncode(await exportRawKey(pair.publicKey));
  return { pair, publicKey };
}
