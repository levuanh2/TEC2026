// The one Node API a test needs (brandGreen.test.ts reads the shipped
// stylesheets). Declared here rather than adding @types/node to the app.
declare module 'node:fs' {
  export function readFileSync(path: URL | string, encoding: 'utf8'): string
}
