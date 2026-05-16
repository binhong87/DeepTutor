// Type stub for the `katex/contrib/mhchem` side-effect module. KaTeX
// ships the implementation but not a `.d.ts`, so TypeScript can't resolve
// the import in strict mode. The module exports nothing — it just patches
// KaTeX with the `\ce{...}` / `\pu{...}` chemistry macros at load time.
declare module "katex/contrib/mhchem";
