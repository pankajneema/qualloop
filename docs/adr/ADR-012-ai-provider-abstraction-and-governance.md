# ADR-012 — AI provider abstraction and governance

- Status: Accepted (2026-10-03); production provider selected, no account yet
- Spec: §4.9, §20 (policy, extraction, 8D assist, NCR helpers, benchmarks), §24.1.3, §6.4 `ai_extractions`

## Context
AI assists only, from background jobs, behind one provider interface (§22, §24.1.3). It never approves/rejects,
closes, changes status, overrides risk, calculates or edits money, or deletes (§20.1). Every workflow must work with AI
unavailable. Reproducibility fields are mandatory (§20.2). Customer documents contain personal data (§21.5) and the
product promises India hosting (§26.2).

## Options considered
| Concern | Options | Recommendation |
| --- | --- | --- |
| LLM | OpenAI API; Anthropic API; Google Gemini (Vertex AI asia-south1); AWS Bedrock in ap-south-1 | **AWS Bedrock (ap-south-1)** first adapter — same cloud/region and IAM as ADR-017, no data leaves the AWS account boundary; verify at P03 which models with JSON-schema/tool output are served in-region (cross-region inference would move data out of India — must be disabled or explicitly accepted) |
| OCR | provider vision model; AWS Textract (ap-south-1); local Tesseract | **text layer first** (`pypdf`/`pdfplumber`), then Textract for scanned PDFs/images; Tesseract as no-cost fallback adapter |
| Abstraction | direct SDK calls; LangChain-type framework; **thin internal interface** | thin interface — no framework dependency |

## Decision
1. `api/app/ai/providers/base.py`: `class LLMProvider(Protocol): def extract(self, *, schema: type[BaseModel], prompt: Prompt, inputs: ...) -> ProviderResult` and `class OCRProvider(Protocol)`. `ProviderResult` carries `output`, `model`, `model_version`, `latency_ms`, `cost_usd_micros`, raw usage.
2. Adapters: `fake.py` (deterministic fixtures; local/CI default), `bedrock.py`, `textract.py`, `tesseract.py`. Selected by `QL_AI_PROVIDER`.
3. Import rule (import-linter): `ai.providers` importable only from `*.jobs` modules; `ai` cannot import `finance`, or any module's `commands`. AI-originated writes use `actor_type='ai'` and are limited to `ai_extractions` (and `ai_suggestions` if approved, A-63); the command framework denies `ai` on every state-changing command.
4. Prompts and JSON schemas are versioned files under `ai/prompts/` and `ai/schemas/` (`prompt_version`, `extraction_version` = file version ids); outputs validated with Pydantic (strict JSON schema); invalid output → retry once, then `review_status='pending'` with empty fields (manual entry).
5. Validation rules (§20.2) are deterministic Python, not AI: expiry after issue, holder fuzzy-match to supplier (rapidfuzz), type matches request, expiry not past (flag), cert-no plausibility regex per type.
6. Data minimisation: only the document bytes/text are sent; no supplier contact data in prompts; provider configured with no training on inputs and no retention where the provider offers it.
7. Benchmarks (§20.5): `api/tests/benchmarks/` runner computes per-field accuracy and flag precision/recall against labelled sets; CI job `ai-bench` blocks merges touching prompts/provider config when gates fail.
8. Voice-to-text at NCR capture uses the browser/OS speech API on the device, not the server AI layer (A-64).
9. **Prompt injection (D-8).** Supplier-written 8D text and document text are untrusted data. They are placed in delimited data blocks, and the system prompt says embedded instructions must be ignored. The model has no tools, no URL fetching and no write access. Output must validate against a fixed JSON schema (flags plus a 3-line summary); anything else is discarded. Output is advisory only: it is shown in the "Suggestion · not applied" box, rendered as escaped text (no HTML/Markdown, links not clickable), and it can never trigger a command. Test: `test_8d_assist_output_is_advisory_and_escaped`.
10. Cost and latency recorded per call; weekly correction rate per field from `corrected_fields` (§20.5 production tracking).

## Consequences
- AI outage only delays suggestions; review UI always allows manual entry.
- Labelled benchmark sets contain customer documents — stored in a restricted bucket prefix, not in git.

## Revisit when
- Benchmark gates fail for the current provider on two consecutive prompt iterations, or
- cost per certificate exceeds a budget set by the human at P03, or in-region model availability changes.

## Human decision (2026-10-03)

No paid services or accounts now; local stand-ins in dev. Production targets (accounts created only when needed, each still subject to CLAUDE.md §5 before use): AWS Bedrock + Textract. India-region (ap-south-1) availability of the chosen models is checked in P03 before any account is opened. Dev uses the `fake` provider (A-91).
