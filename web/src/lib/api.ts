import { CSRF_COOKIE, commandHeaders, newIdempotencyKey, readCookie } from '@/lib/http';
import { describeProblem, type Described, type ProblemFallback } from '@/lib/problem';

/** Same-origin API (ADR-013 item 1): cookies stay first-party and there is no CORS for our own calls. */
export const API_BASE = '/api/v1';

export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;
  readonly retryAfter: number | null;

  constructor(status: number, body: unknown, retryAfter: number | null) {
    super(`API ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
    this.retryAfter = retryAfter;
  }

  describe(fallback?: ProblemFallback): Described {
    return describeProblem(this.body, fallback);
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

function withQuery(path: string, query?: Query): string {
  if (!query) return `${API_BASE}${path}`;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === '') continue;
    params.set(key, String(value));
  }
  const text = params.toString();
  return `${API_BASE}${path}${text ? `?${text}` : ''}`;
}

async function parse(response: Response): Promise<unknown> {
  const raw = await response.text();
  if (!raw) return null;
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    return null;
  }
}

async function send<T>(url: string, init: RequestInit, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, { ...init, signal, credentials: 'same-origin' });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError(0, null, null); // network failure: described by the fallback copy
  }
  const body = await parse(response);
  if (!response.ok) {
    const retry = Number(response.headers.get('Retry-After'));
    const error = new ApiError(
      response.status,
      body,
      Number.isFinite(retry) && retry > 0 ? retry : null,
    );
    // A lost session sends the user to sign in; the sign-in screens themselves handle their own 401.
    if (response.status === 401 && !window.location.pathname.startsWith('/login')) {
      window.location.replace('/login');
    }
    throw error;
  }
  return body as T;
}

export function apiGet<T>(path: string, query?: Query, signal?: AbortSignal): Promise<T> {
  return send<T>(withQuery(path, query), { method: 'GET' }, signal);
}

export function apiPost<T>(
  path: string,
  body: unknown = {},
  options: { idempotencyKey?: string; signal?: AbortSignal } = {},
): Promise<T> {
  const csrf = readCookie(document.cookie, CSRF_COOKIE);
  return send<T>(
    withQuery(path),
    {
      method: 'POST',
      headers: commandHeaders({
        csrf,
        idempotencyKey: options.idempotencyKey ?? newIdempotencyKey(),
      }),
      body: JSON.stringify(body),
    },
    options.signal,
  );
}
