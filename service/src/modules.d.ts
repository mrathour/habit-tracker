// Text modules bundled by Wrangler (wrangler.toml `rules`).
declare module "*.html" {
  const content: string;
  export default content;
}
declare module "*.css" {
  const content: string;
  export default content;
}
