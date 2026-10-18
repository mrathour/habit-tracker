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
  EFFECTIVE_DATE: "{{EFFECTIVE_DATE}}",
  OPERATOR_NAME: "{{OPERATOR_NAME}}",
  CONTACT_EMAIL: "{{CONTACT_EMAIL}}",
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
