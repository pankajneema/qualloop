# QualLoop — Design Spec

Source: the approved design canvas "Supplier Quality OS — UI/UX Design" (design system, samples,
My Work, Supplier Quality Case, Supplier 360, inspector NCR capture, supplier 8D). Brand name in UI: **QualLoop**.
Implement these values as tokens in `web/src/design/tokens.ts`; never hard-code other values.

## Typography
- Families: **IBM Plex Sans** (UI), **IBM Plex Sans Devanagari** (Hindi), **IBM Plex Mono** (IDs, quantities,
  PPM, money — tabular figures).

| Token | Size / line / weight | Use |
| --- | --- | --- |
| display | 32 / 40 / 600 | Reports and PDFs only |
| h1 | 24 / 32 / 600 | Page title, one per screen |
| h2 | 18 / 26 / 600 | Panel and section titles |
| h3 | 15 / 22 / 600 | Field groups, card headers |
| body | 14 / 20 / 400 | Desktop default |
| body-mobile | 16 / 24 / 400 | Phones; inputs never below 16 px |
| caption | 12 / 16 / 500 | Trust signals, metadata |
| label | 11 / 16 / 600, uppercase, +0.06em | Table headers, overlines |
| kpi | 28 / 32 / 500 mono | Headline numbers |
| data | 13 / 20 / 400 mono | IDs, quantities, money in tables |

Devanagari text: +2 px line-height.

## Colour
| Token | Hex | Use |
| --- | --- | --- |
| ink | #101828 | Primary text, nav background |
| ink-2 | #344054 | Body text |
| muted | #475467 | Captions |
| subtle | #667085 | Placeholder, tertiary |
| line | #D0D5DD | Borders |
| line-soft | #E4E7EC | Card borders |
| ground | #F5F6F8 | App background |
| surface | #FFFFFF | Cards |
| action | #1D4ED8 (hover #1E3A8A) | Primary buttons, links |

Status (always shape + colour + word; never red/green alone):
- Severity — Critical: bg #FEE4E2, text #912018, mark #B42318 square · Major: bg #FEF0C7, text #93370D, mark #DC6803 circle · Minor: bg #F2F4F7, text #344054, hollow circle.
- SCAR due-status — On time #D1E9FF/#194185 · Late #FEF0C7/#93370D · Overdue solid #B42318 white text with days · Not yet due #F2F4F7/#344054.
- Certificate validity — Valid blue · Expiring (days shown) amber · Expired #FEE4E2/#912018 · Exception #F4EBFF/#53389E with end date · Not requested dashed outline.
- Risk (system signal) — Low grey · Medium amber · High solid #912018 with score and trend arrow.
- Supplier status (human decision) — outlined chips only; never styled like risk.
- AI suggestion box — bg #F4F3FF, border #D9D6FE, label "Suggestion · not applied".

## Space & layout
- 4 px base; scale 4, 8, 12, 16, 24, 32, 48. Radius 6 controls, 8 cards, 999 pills.
- Borders, not shadows; one soft shadow only for dialogs, menus, sheets.
- Desktop: dark left nav 232 px; content max 1360 px; header (title + one primary action) + work area + context rail.
  < 1024 px rail drops below; < 640 px nav becomes a bottom bar.
- Table rows 40 px (compact 32). Phone targets ≥ 48 px; primary action pinned at bottom.

## Components
- Button: primary (one per view), secondary (outline), ghost, destructive (red outline, never default focus, asks for reason).
- Field: label above, help text below, error text says what to do.
- KpiTile: label · value (mono) · delta vs target · sample · coverage · freshness · "How this was calculated →";
  states Provisional (amber chip + unreconciled qty) and "N/A — insufficient data".
- QueueRow: State chip · What · Why · Owner · Due (mono) · Next action.
- ReasonDialog: states consequence, required reason, button names the exact action.
- StatusChip variants for severity, due-status, validity, risk, supplier status.

## Screens (R1)
- **My Work**: count tiles → grouped queue → rail (exposure cohort, turned-High-risk suppliers, data health).
- **Supplier Quality Case**: header (IDs, severity, status, due-status; Accept primary, Send back secondary),
  6-step progress, tabs (8D response, NCRs, Money, Effectiveness, Messages, History), occurrence/escape/systemic
  cause cards, AI suggestion box, rail (linked NCRs, money on case, supplier messages with delivery status).
- **Supplier 360**: Status block and Risk block separate; score with components and coverage; 6-month PPM bars with
  target line; risk reasons with points; open cases; documents with validity chips; quality contact with consent.
- **Inspector NCR (phone PWA)**: photos → GRN scan prefill → qty checked → defects with per-defect qty steppers →
  severity segmented control → customer-disruption toggle → pinned "Submit · N rejected"; elapsed timer.
- **Supplier 8D (phone, no login)**: customer company name, EN/हिन्दी toggle, 4-step progress, due date,
  draft autosave, plain-language cause questions with examples.
- **Samples to match**: WhatsApp template, OTP screen, Hindi 8D, attribution dialog, use-as-is reason dialog,
  effectiveness no-data decision, empty state, failure messages, calculation drill-down, monthly report PDF page 1.

## The 10 UX rules
1. Home is a to-do list, not a chart wall.
2. 30 seconds to log a rejection.
3. Suppliers never log in (link + OTP, one SCAR per session, low-end phone on 3G).
4. Every number shows its evidence.
5. Never fake confidence (N/A and Provisional are designed states).
6. Risk and status never share a badge.
7. The case is the unit of work.
8. Consequential actions ask why.
9. AI suggests in a visibly separate box and never auto-applies.
10. Plant words, two languages (GRN, IQC, 8D, debit note; English ⇄ हिन्दी).

## Copy rules
- Errors: what happened · what we did · what you can do. Never "Something went wrong".
- Buttons are verbs naming the action ("Issue SCAR", "Approve use-as-is").
- Dates in plant timezone, format "3 Oct 2026"; money in ₹ with Indian grouping (₹4,20,000).
