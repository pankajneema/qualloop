/**
 * Late-bound module access for tests written before the module exists (P02 test contract, section 5).
 * A missing module makes only the tests that need it fail, and `tsc` stays clean because the path is not a
 * static import. Always pass an `@/...` alias path: a relative path would resolve against this file.
 */
export async function load<T>(path: string): Promise<T> {
  return (await import(/* @vite-ignore */ path)) as T;
}
