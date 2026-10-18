import { createHash } from "node:crypto";
import type { Plugin } from "vite";

/**
 * Adds a strict Content-Security-Policy to the built index.html.
 *
 * The production build is a single file loaded over file://, with every script inlined by
 * vite-plugin-singlefile. This plugin runs after it, hashes each inline script, and allows only
 * those hashes, so injected markup (for example a Notion task name) can never run as script.
 * Styles allow 'unsafe-inline' because ECharts sets inline styles on its tooltips.
 */
export function contentSecurityPolicy(): Plugin {
  return {
    name: "habit-tracker:csp",
    apply: "build",
    enforce: "post",
    generateBundle: {
      order: "post",
      handler(_options, bundle) {
        const page = bundle["index.html"];
        if (page?.type !== "asset" || typeof page.source !== "string") {
          this.error("index.html was not found in the bundle");
        }
        page.source = withPolicy(page.source);
      },
    },
  };
}

const INLINE_SCRIPT = /<script\b(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi;

export function buildPolicy(html: string): string {
  const hashes = [...html.matchAll(INLINE_SCRIPT)].map(
    (match) =>
      `'sha256-${createHash("sha256")
        .update(match[1] ?? "", "utf8")
        .digest("base64")}'`,
  );
  return [
    "default-src 'none'",
    `script-src ${hashes.length > 0 ? hashes.join(" ") : "'none'"}`,
    "style-src 'unsafe-inline'",
    "img-src data: blob:",
    "font-src data:",
    "connect-src 'none'",
    "object-src 'none'",
    "base-uri 'none'",
    "form-action 'none'",
  ].join("; ");
}

const CHARSET_META = /<meta\s+charset=[^>]*>/i;

/** Insert the policy right after <meta charset>, which must stay first in <head>. */
export function withPolicy(html: string): string {
  const meta = `<meta http-equiv="Content-Security-Policy" content="${buildPolicy(html)}" />`;
  if (CHARSET_META.test(html)) {
    return html.replace(CHARSET_META, (charset) => `${charset}\n    ${meta}`);
  }
  if (/<head>/i.test(html)) {
    return html.replace(/<head>/i, `<head>\n    ${meta}`);
  }
  throw new Error("index.html has no <head> to add the Content-Security-Policy to");
}
