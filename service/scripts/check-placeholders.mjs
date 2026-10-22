// Runs before `npm run deploy`: refuses to publish pages that still contain {{PLACEHOLDER}}s.
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/pages.ts", import.meta.url), "utf8");
const values = source.slice(source.indexOf("PAGE_VALUES"), source.indexOf("} as const;"));
const left = [...values.matchAll(/\{\{([A-Z_]+)\}\}/g)].map((match) => match[1]);
if (left.length > 0) {
  console.error(`Not deploying: fill in ${left.join(", ")} in service/src/pages.ts first.`);
  process.exit(1);
}
console.log("Page values are filled in.");
