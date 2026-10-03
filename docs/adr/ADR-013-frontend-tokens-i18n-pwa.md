# ADR-013 — Frontend architecture, design tokens, i18n, PWA

- Status: Proposed
- Spec: §4.3 (30-second capture), §5.3 (no native/offline), §9 C7 (supplier pages on low-end Android/3G), §22 (Next.js, TypeScript, Tailwind, PWA), DESIGN_SPEC.md

## Context
Three audiences: desktop internal users (dense tables, case page), inspectors on mid-range Android (PWA capture ≤ 30 s),
suppliers with no account on low-end phones over 3G, in English and Hindi. DESIGN_SPEC defines tokens that must live in
`web/src/design/tokens.ts` and must not be hard-coded elsewhere.

## Options considered
| Concern | Options | Chosen |
| --- | --- | --- |
| Framework | **Next.js App Router** (mandated) | — |
| Data fetching | fetch in components; **TanStack Query** client-side + typed client from OpenAPI (`openapi-typescript` + `openapi-fetch`) | TanStack Query for internal app; supplier pages use plain server components + minimal client JS |
| Styling | CSS modules; **Tailwind** (mandated) with theme generated from `tokens.ts` | Tailwind; lint rule bans arbitrary values (`[#…]`, `[13px]`) |
| i18n | react-i18next; **next-intl** | next-intl (App Router native, server + client) |
| PWA | next-pwa / serwist; **hand-written manifest (`app/manifest.ts`) + small service worker** caching app shell and fonts | hand-written, no offline data (offline mode is excluded, §5.3) |
| Forms | **react-hook-form + zod** (schemas generated from OpenAPI types where possible) | — |

## Decision
1. Routing: `(app)/…` internal (session cookie), `capture/` inspector flow (PWA start_url), `s/[token]/…` supplier pages.
   API is same-origin `/api/v1` (ALB routes), so cookies are first-party; no API routes in Next.js.
2. Tokens: `tokens.ts` exports typography, colours (incl. every status colour pair), spacing (4…48), radius (6/8/999),
   layout (nav 232, content 1360, breakpoints 640/1024, row heights 40/32, phone targets 48). `tailwind.config.ts` builds
   the theme from it; a vitest test asserts values equal DESIGN_SPEC; ESLint forbids hex literals outside `tokens.ts`.
3. Fonts: `next/font` self-hosting IBM Plex Sans, IBM Plex Sans Devanagari, IBM Plex Mono (tabular figures); Devanagari
   +2 px line height via `:lang(hi)`.
4. i18n: `messages/en.json`, `messages/hi.json`; locale in cookie `ql_locale` (internal users) and an EN/हिन्दी toggle on
   supplier pages; CI check that both files have identical keys; supplier-facing namespaces must be 100% translated.
5. Supplier pages budget: ≤ 150 kB JS gzipped on first load, server-rendered, works at 360 px; drafts autosave every
   field blur + 10 s via `POST /supplier/scar/response/draft`.
6. Inspector capture: photo via `<input type="file" accept="image/*" capture="environment">`, client-side resize to
   ≤ 1600 px JPEG before upload; GRN scan via `BarcodeDetector` where available, else manual entry; elapsed timer;
   `capture_started_at` set when the screen opens.
7. Money/quantities rendered with `Intl.NumberFormat('en-IN')`; dates in plant timezone ("3 Oct 2026").
8. Accessibility: axe checks in Playwright from P08; targets ≥ 48 px on phone.

## Consequences
- Generated API types make backend schema changes visible as TypeScript errors in CI.
- No offline capture; flaky connectivity is handled by retrying uploads and keeping form state locally until submit.

## Revisit when
- Inspector median capture > 30 s in pilot measurement (§25) because of connectivity (→ offline capture is R2 §28.7), or
- supplier page first load > 5 s p75 on 3G (Lighthouse throttled) despite the JS budget.
