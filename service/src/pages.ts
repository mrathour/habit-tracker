import home from "../pages/home.html";
import privacy from "../pages/privacy.html";
import styles from "../pages/style.css";
import support from "../pages/support.html";
import terms from "../pages/terms.html";

/**
 * Values that appear in the legal and support pages. Set here, in one place, so a change is
 * reviewed in a single diff.
 */
export const PAGE_VALUES = {
  EFFECTIVE_DATE: "18 October 2026",
  OPERATOR_NAME: "Mayank Rathour",
  CONTACT_EMAIL: "mrathour1997@gmail.com",
  GOVERNING_LAW:
    "These terms are governed by the laws of India, and the courts at New Delhi have jurisdiction.",
} as const;

interface Page {
  title: string;
  body: string;
}

export const PAGES: Readonly<Record<string, Page>> = {
  "/": { title: "Habit Tracker", body: home },
  "/privacy": { title: "Privacy policy · Habit Tracker", body: privacy },
  "/terms": { title: "Terms of use · Habit Tracker", body: terms },
  "/support": { title: "Support · Habit Tracker", body: support },
};

export const STYLESHEET_PATH = "/style.css";
export const STYLESHEET = styles;

function fillValues(html: string): string {
  return html.replace(/\{\{([A-Z_]+)\}\}/g, (placeholder, key: string) =>
    key in PAGE_VALUES ? PAGE_VALUES[key as keyof typeof PAGE_VALUES] : placeholder,
  );
}

const NAV = `<nav><a href="/" class="brand">Habit Tracker</a>
<span><a href="/privacy">Privacy</a><a href="/terms">Terms</a><a href="/support">Support</a></span></nav>`;

export function renderPage(page: Page): string {
  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>${page.title}</title>
<link rel="stylesheet" href="${STYLESHEET_PATH}">
</head>
<body>
${NAV}
<main>
${fillValues(page.body)}
</main>
</body>
</html>
`;
}

/** Pages have no scripts, forms or third-party content. */
export const PAGE_CSP =
  "default-src 'none'; style-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'";

/** Escapes text placed in element content (never in attributes). */
function escapeHtml(text: string): string {
  return text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function htmlResponse(html: string, status = 200): Response {
  return new Response(html, {
    status,
    headers: { "Content-Type": "text/html; charset=utf-8", "Content-Security-Policy": PAGE_CSP },
  });
}

/** A browser-facing error, for problems the app can't be told about. */
export function errorPage(status: number, title: string, message: string): Response {
  const body = `<h1>${escapeHtml(title)}</h1>\n<p class="lead">${escapeHtml(message)}</p>\n<p class="links"><a href="/support">Get help</a></p>`;
  return htmlResponse(renderPage({ title: `${escapeHtml(title)} · Habit Tracker`, body }), status);
}
