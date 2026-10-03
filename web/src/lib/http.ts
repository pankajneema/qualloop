/** Request helpers (API.md 1.2 CSRF double submit, 1.6 idempotency). */

export const CSRF_COOKIE = 'ql_csrf';

export function readCookie(cookieHeader: string, name: string): string | null {
  for (const part of cookieHeader.split(';')) {
    const index = part.indexOf('=');
    if (index < 0) continue;
    if (part.slice(0, index).trim() !== name) continue;
    const raw = part.slice(index + 1).trim();
    try {
      return decodeURIComponent(raw);
    } catch {
      return raw;
    }
  }
  return null;
}

export function commandHeaders(input: {
  csrf: string | null;
  idempotencyKey?: string;
}): Record<string, string> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };
  if (input.csrf) headers['X-CSRF-Token'] = input.csrf;
  if (input.idempotencyKey) headers['Idempotency-Key'] = input.idempotencyKey;
  return headers;
}

/** A hyphenated UUID. `crypto.randomUUID` only exists in secure contexts, so fall back to getRandomValues. */
export function newIdempotencyKey(): string {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID();
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40;
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80;
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
