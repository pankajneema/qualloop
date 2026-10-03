import { NextResponse, type NextRequest } from 'next/server';

/**
 * The origin browsers PUT import files to (a presigned URL on the public S3 endpoint, A-120). It is added to
 * `connect-src` and nowhere else. Configure it with `QL_S3_PUBLIC_ENDPOINT_URL`, the same variable the API signs with.
 */
export function uploadOrigin(
  value: string | undefined = process.env.QL_S3_PUBLIC_ENDPOINT_URL,
): string {
  if (!value) return '';
  try {
    return new URL(value).origin;
  } catch {
    return '';
  }
}

/** Screens that need a session. Without the session cookie the proxy sends the browser to /login. */
export const PROTECTED_PREFIXES = ['/suppliers', '/parts', '/imports'] as const;
export const SESSION_COOKIE = 'ql_session';

export function isProtectedPath(pathname: string): boolean {
  return PROTECTED_PREFIXES.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

/** Per-request nonce CSP (Next 16 "proxy", formerly middleware). Next applies the nonce to its own scripts. */
export function buildCsp(nonce: string, dev: boolean, uploadHost: string = ''): string {
  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${dev ? " 'unsafe-eval'" : ''}`,
    // React sets inline style attributes (design-token CSS variables), so styles keep 'unsafe-inline'.
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self'", // next/font self-hosts the Plex families
    `connect-src 'self'${uploadHost ? ` ${uploadHost}` : ''}${dev ? ' ws: wss:' : ''}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join('; ');
}

export function proxy(request: NextRequest) {
  const nonce = btoa(crypto.randomUUID());
  const csp = buildCsp(nonce, process.env.NODE_ENV !== 'production', uploadOrigin());
  if (isProtectedPath(request.nextUrl.pathname) && !request.cookies.has(SESSION_COOKIE)) {
    // Redirect to the host the browser used (the dev server may think it is 0.0.0.0).
    const host = request.headers.get('x-forwarded-host') ?? request.headers.get('host');
    const proto =
      request.headers.get('x-forwarded-proto') ?? request.nextUrl.protocol.replace(':', '');
    const target = host ? new URL('/login', `${proto}://${host}`) : new URL('/login', request.url);
    const redirect = NextResponse.redirect(target);
    redirect.headers.set('Content-Security-Policy', csp);
    return redirect;
  }
  const headers = new Headers(request.headers);
  headers.set('x-nonce', nonce);
  headers.set('Content-Security-Policy', csp);
  const response = NextResponse.next({ request: { headers } });
  response.headers.set('Content-Security-Policy', csp);
  return response;
}

export const config = {
  matcher: [
    {
      source: '/((?!_next/static|_next/image|favicon.ico).*)',
      missing: [{ type: 'header', key: 'next-router-prefetch' }],
    },
  ],
};
