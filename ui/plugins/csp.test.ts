import { createHash } from "node:crypto";

import { describe, expect, it } from "vitest";

import { buildPolicy, withPolicy } from "./csp.ts";

const hash = (text: string) => `'sha256-${createHash("sha256").update(text).digest("base64")}'`;

describe("content security policy", () => {
  it("allows exactly the inline scripts in the page", () => {
    const html = `<head><script type="module">console.log(1)</script><script>a()</script></head>`;
    const policy = buildPolicy(html);
    expect(policy).toContain(`script-src ${hash("console.log(1)")} ${hash("a()")}`);
    expect(policy).not.toContain("unsafe-eval");
    const scriptSrc = policy.split("; ").find((d) => d.startsWith("script-src")) ?? "";
    expect(scriptSrc).not.toContain("unsafe-inline");
    expect(policy).toContain("default-src 'none'");
    expect(policy).toContain("connect-src 'none'");
  });

  it("ignores external scripts and blocks all scripts when there are none", () => {
    expect(buildPolicy(`<script src="x.js"></script>`)).toContain("script-src 'none'");
  });

  it("goes right after <meta charset>", () => {
    const html = `<html><head>\n<meta charset="UTF-8" />\n<title>x</title></head></html>`;
    const result = withPolicy(html);
    expect(result).toMatch(
      /<meta charset="UTF-8" \/>\n\s+<meta http-equiv="Content-Security-Policy"/,
    );
  });

  it("falls back to the start of <head>", () => {
    expect(withPolicy("<head><title>x</title></head>")).toMatch(
      /^<head>\n\s+<meta http-equiv="Content-Security-Policy"/,
    );
  });

  it("fails loudly without a <head>", () => {
    expect(() => withPolicy("<body></body>")).toThrow("no <head>");
  });
});
