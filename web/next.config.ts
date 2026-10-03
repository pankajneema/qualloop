import type { NextConfig } from 'next';
import createNextIntlPlugin from 'next-intl/plugin';

const withNextIntl = createNextIntlPlugin('./src/i18n/request.ts');

const securityHeaders = [
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'X-Frame-Options', value: 'DENY' },
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
];

// Camera is needed only by the inspector capture flow (GRN barcode scan, ADR-013); nowhere else.
const permissions = (camera: string) => ({
  key: 'Permissions-Policy',
  value: `camera=${camera}, microphone=(), geolocation=()`,
});
// CSP (nonce-based, frame-ancestors 'none') is set per request in src/proxy.ts.
const hsts = { key: 'Strict-Transport-Security', value: 'max-age=31536000; includeSubDomains' };
const production = process.env.NODE_ENV === 'production';

// Dev only: same-origin /api/v1 is routed by the load balancer in staging/prod (ADR-013).
const apiProxyTarget = process.env.QL_API_PROXY_TARGET;

const nextConfig: NextConfig = {
  output: 'standalone',
  poweredByHeader: false,
  async headers() {
    const common = production ? [...securityHeaders, hsts] : securityHeaders;
    return [
      { source: '/capture/:path*', headers: [...common, permissions('(self)')] },
      { source: '/((?!capture).*)', headers: [...common, permissions('()')] },
    ];
  },
  async rewrites() {
    return apiProxyTarget
      ? [{ source: '/api/:path*', destination: `${apiProxyTarget}/api/:path*` }]
      : [];
  },
};

export default withNextIntl(nextConfig);
