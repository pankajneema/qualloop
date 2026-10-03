/**
 * Turns an `application/problem+json` body (API.md 1.4) into text for people. The API writes "what happened, what we
 * did, what you can do"; this only adds a fallback of the same shape when the body is unreadable, so a screen never
 * says "Something went wrong". Callers pass translated fallbacks; the English defaults serve tests and logs.
 */

export type Described = { title: string; detail: string; fields: Record<string, string> };

export type ProblemFallback = { title: string; detail: string; reference: string };

export const DEFAULT_FALLBACK: ProblemFallback = {
  title: 'We could not finish that',
  detail:
    'The server sent an answer we could not read. Nothing was saved. Check your connection and try again; if it keeps happening, tell support.',
  reference: 'Reference',
};

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

/** `body.gstin` and `gstin` both name the field `gstin`. */
function fieldName(raw: string): string {
  return raw.replace(/^body[.›>]\s*/i, '').trim();
}

export function describeProblem(
  body: unknown,
  fallback: ProblemFallback = DEFAULT_FALLBACK,
): Described {
  const record = asRecord(body);
  const fields: Record<string, string> = {};
  if (record && Array.isArray(record.errors)) {
    for (const entry of record.errors) {
      const e = asRecord(entry);
      const name = text(e?.field);
      const message = text(e?.message);
      if (name && message) fields[fieldName(name)] = message;
    }
  }
  const title = text(record?.title) || fallback.title;
  let detail = text(record?.detail) || fallback.detail;
  const status = typeof record?.status === 'number' ? record.status : 0;
  const requestId = text(record?.request_id);
  if (status >= 500 && requestId) detail = `${detail} ${fallback.reference}: ${requestId}.`;
  return { title, detail, fields };
}
