# Take-Home Exercise — Forward Deployed Engineer (Data, ML & AI)

## The point of this exercise

We don't want to see how fast you can type code. We want to see how you **direct AI to build a production-shaped system from a spec** — the actual day-to-day of a Forward Deployed Engineer. You will use Claude Code, Cursor, Copilot, or whatever AI tooling you prefer. That is not only allowed, it is the assignment.

**Timebox: ~1 hour of active work.** Please don't spend a weekend on this. We would rather see a tight, well-specified, honestly-scoped 60-minute build than a sprawling unfinished platform. If you hit the wall at 60 minutes, stop and write down what you'd do next.

You may pick **either track** below. Both are graded on the same rubric.

---

## The scenario

You've just been embedded with **CloudNova**, a B2B SaaS company. On day one their finance lead hands you a messy invoice-ledger export and says: *"We want to ask questions about our revenue and customers in plain English and actually trust the answers. Can you show us something by end of day?"*

That's the whole brief. Your job is to turn that vague ask into a spec, then have AI build to the spec, then show it works and prove you know where it breaks.

Everything you need is in [`/data`](./data):
- [`cloudnova_invoices.csv`](./data/cloudnova_invoices.csv) — ~5k invoice rows, intentionally dirty (nulls, inconsistent plan/status categories, full + near-duplicate rows, mixed date formats, amounts as `"$4,900.00"` strings, negative refunds, malformed emails).
- [`BUSINESS_CONTEXT.md`](./data/BUSINESS_CONTEXT.md) — your **customer briefing**: pricing rules, what counts as recognized revenue, how MRR is defined, the known data-quality landmines, and a list of questions a stakeholder would actually ask. **Read this first** — it's where the business logic lives, and your spec should be driven by it.

If you'd rather bring your own domain dataset, that's fine — just keep it small and note where it came from. But the provided data is designed so the interesting work is in the modeling and the business logic, not in sourcing data.

---

## Pick one track

### Track A — Agentic RAG over the dataset
Build a small **retrieval-augmented Q&A agent** that answers natural-language questions about CloudNova's invoices and accounts.
- Ingest + chunk + embed the data into a vector store (Chroma, FAISS, LanceDB, pgvector — your call; local is fine).
- A question-answering interface: CLI or a thin API endpoint (`POST /ask`). No frontend required.
- Answers must **cite** which rows/records they came from.
- It should handle at least a few of the stakeholder questions in `BUSINESS_CONTEXT.md` — including ones that require applying business rules (e.g. only `paid` invoices count as revenue), not just semantic lookup. Tell us honestly where pure RAG struggles with the aggregation-style questions.
- Use a framework if you like (LangChain, LlamaIndex, DSPy) or roll it by hand — justify the choice in the README.

### Track B — Spec-driven data pipeline + query agent
Build a **cleaning-and-modeling pipeline** plus a natural-language-to-query layer.
- Write a spec for the cleaned schema (types, constraints, dedup rules, category/status normalization, date parsing, FX→USD, MRR derivation per `BUSINESS_CONTEXT.md`).
- Have AI generate the transformation code (pandas/Polars/PySpark/dbt/SQL — your call) from that spec.
- Expose a natural-language question interface that translates a question into a query over the cleaned data and returns the answer with the generated query shown.
- Correctly answering the revenue/MRR/churn stakeholder questions in `BUSINESS_CONTEXT.md` is the bar here — that's where the business logic gets tested.

Either track should be **runnable from a single command** after setup (`python -m app`, etc.).

---

## What we actually care about (the rubric)

You are scored on these, roughly in priority order:

1. **Spec-Driven Development.** Did you write the spec *first* and drive the AI from it? We want to see the spec as an artifact, not reverse-engineered after the fact.
2. **How you used AI.** We read your `.claude/` (or equivalent) config and prompt history. Good prompting, good context-setting, and good judgment about when to override the AI all score highly.
3. **Evaluation & honesty about limits.** A small **eval harness** with a handful of question→expected-answer cases beats a demo that only works on the happy path. Tell us the failure modes.
4. **Production instincts.** Error handling, config over hardcoding, secrets not committed, sane project structure, a diagram that matches the code.
5. **Communication.** The README should let a customer stakeholder understand what you built and why in 3 minutes.

We are **not** scoring: model accuracy leaderboards, UI polish, cloud deployment, or lines of code.

---

## Required deliverables — a GitHub repo containing:

> A submission missing items 1–5 is considered incomplete. Item 6 is a differentiator.

1. **`README.md`** with:
   - What it does and how to run it (setup + the single demo command).
   - The **spec** you wrote (inline or linked in `/specs`).
   - Key design decisions and trade-offs, and **what you'd do with another day**.
   - Known limitations and failure modes (be honest — this scores *higher* than pretending there are none).

2. **`.claude/` directory** (or `CLAUDE.md`, `.cursorrules`, `copilot-instructions.md` — whatever your tool uses) showing how you configured and steered the AI. This is a first-class artifact for this role, not an afterthought. If your tool keeps a prompt/session log, include a trimmed version under `/docs`.

3. **A system architecture diagram** committed to the repo (`/docs/architecture.*`). An `.excalidraw`, Mermaid-in-README, PNG, or draw.io export are all fine. It must reflect what you actually built — data flow from raw input → processing → store → query/answer.

4. **`/specs`** — the spec(s) that drove the build (schema spec, eval spec, API contract — whatever applies to your track).

5. **An eval harness** (`/evals` or `tests/`) — a runnable script with a small set of cases and a way to see pass/fail. Even 5 cases is enough; seed them from the stakeholder questions in `BUSINESS_CONTEXT.md`. Include one case you *expect to fail* and say why.

6. **(Bonus) One "production hardening" touch** — e.g. a Dockerfile, a CI check (GitHub Action running the evals), input validation/guardrails, caching, or a cost/latency measurement. Pick one; don't gold-plate.

### Submission
- Push to a **public GitHub repo** (or private + invite the addresses we give you) and reply with the link.
- Include a `git` history that reflects the real build — small honest commits are better than one giant "initial commit."
- **Optional but encouraged:** a 3–5 minute Loom/screen recording walking us through the repo and a live run. This often does more for a candidate than the code itself.

---

## Ground rules & tips

- **Use AI heavily. Tell us how.** The differentiator is *direction*, not autocomplete.
- **Scope down aggressively.** A working narrow slice with evals beats a broad broken thing.
- **Don't commit secrets.** Use `.env` + `.env.example`. If an API key is required to run, say so in the README.
- **If you run out of time,** ship what works and write the rest as a "Next steps" section. Knowing where to stop is part of the job.
- Questions about the exercise? Reply and ask — how you handle ambiguity is itself signal.

Good luck — we're looking forward to seeing how you work.
