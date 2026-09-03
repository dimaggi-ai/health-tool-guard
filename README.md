# DIMAGGI Tool Guard — Runtime Policy Firewall for Gemma 4 Agents

[![License: AGPL v3 or Commercial](https://img.shields.io/badge/License-AGPL_v3_%7C_Commercial-blue?style=flat-square)](#license)
[![Built with Gemma 4](https://img.shields.io/badge/Built_with-Gemma_4-4285F4?style=flat-square)](https://ai.google.dev/gemma/terms)
[![Tests: 14 passing](https://img.shields.io/badge/tests-14_passing-brightgreen?style=flat-square)](tests/test_policies.py)
[![Live Demo](https://img.shields.io/badge/Live_Demo-dimaggi.ai%2Fhealth--tool--guard-orange?style=flat-square)](https://dimaggi.ai/health-tool-guard/)

> **Runtime policy firewall for AI agents — intercepts every tool call before execution. Deterministic checks in <15 ms, Gemma 4 hybrid reasoning over live openFDA labels in ~700 ms. Every decision SHA-256 + HMAC-chained and independently verifiable. 14/14 policy tests pass; tamper-detection proven.**
> Submission for the **Kaggle × Google DeepMind Gemma 4 Good Hackathon** — Safety & Trust track.

---

## What It Does

Tool Guard intercepts every tool call an AI agent makes, **before execution**, and runs three actions on each one:

| Action | What it does | When |
|---|---|---|
| **⚖ DECIDE** | Evaluates the call against a configurable policy set. Deterministic checks finish in <15 ms; Gemma 4 hybrid checks finish in 700–900 ms. | Always |
| **⛓ AUDIT** | Writes the decision to a SHA-256 + HMAC-signed chain. Tamper-evident, court-defensible, independently verifiable. | Every decision |
| **🙋 ESCALATE** | Routes the request to a human reviewer when Gemma 4 cannot be trusted (unsupported language, low confidence, ambiguous safety call). | When DECIDE returns ESCALATE |

The submission video demonstrates two cases live, end to end:

1. **Luganda audio → DENY.** A patient in Kampala speaks Luganda. Gemma 4 transcribes the audio. The agent proposes ibuprofen — which cross-reacts with the patient's documented aspirin allergy. Tool Guard pulls the openFDA ibuprofen label in real time, Gemma 4 reasons over it, and the call is denied before the prescription is written. Decision is hashed, signed, and chained.

2. **Acholi audio → ESCALATE.** A patient speaks Acholi — a Nilotic language with ~1 million speakers, **not in any WHO/FDA-cleared clinical model**. Tool Guard refuses to hallucinate what it cannot verify, escalates the request to a human clinician (Dr. K. Okello, Gulu Regional), and records the ESCALATE in the same audit chain.

The same Gemma 4 model also runs **on-device**. A third demo, running on a phone in airplane mode with openFDA labels embedded in the system prompt, shows the gate working offline in Spanish.

---

## Architecture

### System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│          AI AGENTS  (LangChain / AutoGPT / MCP / any framework)             │
└────────────────────────────────────┬────────────────────────────────────────┘
                                     │  tool call: {name, params, context}
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│            TOOL GUARD PROXY   [port 8092]                                   │
│            Intercepts every tool call before execution                      │
└──────────────────┬───────────────────────────────────┬──────────────────────┘
                   │                                   │
       ┌───────────▼──────────────┐      ┌─────────────▼────────────────┐
       │  DETERMINISTIC  < 15 ms  │      │  GEMMA 4 E4B HYBRID < 900 ms │
       │  (pure logic, no model)  │      │  (LLM reasoning via Ollama)  │
       │                          │      │                              │
       │  • clinical-scope-lock   │      │  • contraindication-check    │
       │  • pii-boundary          │      │  • draft-only-mode           │
       │  • confidence-gate       │      │  • lingua-terminology-lock   │
       │  • lingua-language-match │      │                              │
       │  • lingua-script-guard   │      │  Queries live:               │
       │  • no-public-actions     │      │  • openFDA drug labels       │
       │  • exfiltration-guard    │      │  • PubMed clinical evidence  │
       │                          │      │                              │
       │                          │      │  Returns structured JSON:    │
       │                          │      │  decision + reasoning +      │
       │                          │      │  confidence + why_hybrid     │
       └───────────┬──────────────┘      └─────────────┬────────────────┘
                   └───────────────┬───────────────────┘
                                   │
                                   ▼
            ┌──────────────────────────────────────────┐
            │            DECISION ROUTER               │
            │                                          │
            │  ALLOW    → forward to tool executor     │
            │  DENY     → block + structured refusal   │
            │  REDACT   → mask PII + allow sanitised   │
            │  ESCALATE → route to human review queue  │
            │  FLAG     → allow + annotate audit log   │
            └───────────────────┬──────────────────────┘
                                │
            ┌───────────────────▼──────────────────────┐
            │          SHA-256 AUDIT CHAIN             │
            │  Every decision appended as:             │
            │  { decision, policy_triggered, latency,  │
            │    explanation, nonce, timestamp,        │
            │    hash = SHA256(record),                │
            │    prev_hash,  ← tamper-evident chain    │
            │    hmac = HMAC-SHA256(secret, record) }  │
            └───────────┬───────────────┬──────────────┘
                        │               │
            ┌───────────▼──────┐  ┌─────▼────────────────────────┐
            │  TOOL EXECUTOR   │  │  ANGULAR DASHBOARD           │
            │  (downstream)    │  │                              │
            │  Only if ALLOW   │  │  ▶ Demo · scenarios          │
            │  or REDACT       │  │  🏥 Clinical · 💊 Drug       │
            │                  │  │  🌍 Lingua · ⛓ Audit Chain   │
            └──────────────────┘  └──────────────────────────────┘
```

### Request Lifecycle — Luganda demo, end to end

```
  Patient audio (Luganda) ──► /transcribe ──► English text (~27 tokens)
                                  │
                                  ▼ agent drafts Luganda response with "Ibuprofen 400mg…"
                                  │
  t=0ms        ┌─────────────────────────────────────────────────────┐
               │  /evaluate  receives: recommend_care_pathway(...)   │
               │  input_lang=lg, output_lang=lg, allergies=aspirin   │
               └────────────────────┬────────────────────────────────┘
                                    │
  t=2ms        ┌─────────────────────▼───────────────────────────────┐
               │  DETERMINISTIC PASS                                 │
               │   • clinical-scope-lock     → PASS                  │
               │   • pii-boundary            → PASS (no PII)         │
               │   • confidence-gate         → PASS (0.91)           │
               │   • lingua-language-match   → PASS (lg=lg)          │
               │   • lingua-script-guard     → PASS                  │
               │   • no-public-actions       → PASS                  │
               │   → fall through to HYBRID                          │
               └────────────────────┬────────────────────────────────┘
                                    │
  t=8ms        ┌────────────────────▼────────────────────────────────┐
               │  GEMMA 4 HYBRID  contraindication-check             │
               │   • Fetch openFDA: api.fda.gov/drug/label?ibuprofen │
               │     → "may cause severe allergic reaction in        │
               │        people allergic to aspirin"                  │
               │   • Prompt: patient + label + clinical guideline    │
               │   • Gemma 4 reasons over the joined context         │
               │   • Returns: DENY · NSAID × aspirin × AERD          │
               └────────────────────┬────────────────────────────────┘
                                    │
  t=634ms      ┌────────────────────▼────────────────────────────────┐
               │  DECISION: DENY · contraindication-check · HYBRID   │
               │  hash:      sha256_a4f3c891…                        │
               │  prev_hash: ← previous record's hash                │
               │  hmac:      hmac_7f940eb0…                          │
               └────────────────────┬────────────────────────────────┘
                                    │
  t=635ms                           ▼
           Agent receives DENY. Drug never dispatched. Audit chain grew by 1.
           A clinician sees the decision in real time on the dashboard.
```

**Typical warm latencies:**

| Path | Trigger | Latency |
|------|---------|---------|
| Deterministic only | Rule match on first check | < 3 ms |
| Deterministic only | All 7 rules pass | < 15 ms |
| Deterministic ESCALATE | Unsupported language | ~ 8 ms |
| Hybrid | Deterministic passes, Gemma 4 needed | 700–900 ms (consumer GPU; multi-second on CPU) |
| Hybrid (cold) | First call after Gemma idle | 2,000–3,000 ms |

---

## Decision Outcomes

| Outcome | Description |
|---------|-------------|
| **ALLOW** | Tool call passes all policies; forwarded to the underlying tool executor unchanged. |
| **DENY** | Tool call violates a hard policy; blocked immediately with a structured refusal + Gemma 4 reasoning. |
| **REDACT** | Tool call allowed but the response is sanitised — PII or out-of-scope fields are removed before the agent sees them. |
| **ESCALATE** | Tool call routed to a human reviewer (low confidence, unsupported language, or safety-edge case). |
| **FLAG** | Tool call proceeds but the audit record is annotated for downstream review. |

---

## HTTP Endpoints

> Bound to port **8080** under the Docker quick start; port **8092** in the native [SETUP.md](SETUP.md) flow.

| Endpoint | Purpose | Path / Model |
|---|---|---|
| `GET /health` | Liveness + model status | Returns `{status, model, gemma_loaded, idle_seconds}` |
| `POST /evaluate` | Single tool-call decision | Deterministic + Gemma 4 hybrid; live openFDA fetch on contraindication checks |
| `POST /transcribe` | Multilingual translation | Gemma 4 translates patient utterance (lg / sw / hi / ar / bn / tl / fr / es / pt) → English. Used by the dashboard's "transcription panel" beat. |
| `POST /agent` | Full agent run | Runs an agent loop with all policies enforced |
| `POST /load` / `POST /unload` | Gemma 4 lifecycle | Explicit warm-up / unload for the demo |
| `POST /search` | openFDA lookup | Direct drug-label search used for proof-of-grounding |
| `GET /model` | Model introspection | Returns the loaded model tag |

**On audio in the demo:** Gemma 4 E4B is a text-only model. The submission video plays human-recorded audio (Luganda, Acholi, Spanish) for multimodal narrative impact, while the system processes the same content as Unicode text via `/transcribe` and `/evaluate`. Audio-to-text STT is documented as a Limitation below; the multilingual reasoning step on text is real Gemma 4 inference.

---

## 10 Languages / 5 Scripts

Lingua policies enforce language-level safety across multilingual deployments. The certified-language set defines which languages Gemma 4 may serve directly and which must be escalated to a human.

| Language | Code | Script | Tool Guard treatment |
|---|---|---|---|
| English | en | Latin | Certified |
| Swahili | sw | Latin | Certified |
| Hindi | hi | Devanagari | Certified |
| Arabic (MSA) | ar | Arabic (RTL) | Certified |
| Bengali | bn | Bengali | Certified |
| Tagalog | tl | Latin | Certified |
| French | fr | Latin | Certified |
| Spanish | es | Latin | Certified |
| Portuguese | pt | Latin | Certified |
| Luganda | lg | Latin | Certified |
| **Acholi** | **ach** | **Latin** | **Escalate** (Gemma 4 cannot verify reliably; PMC11729812 reports 36–76% translation accuracy for under-resourced languages) |
| Amharic | am | Ethiopic | Script-guarded |
| Quechua | qu | Latin | Demo only |

Script detection runs deterministically via Unicode block analysis in under 5 ms. Semantic terminology verification (e.g., Tagalog clinical terms) uses Gemma 4 E4B.

---

## Repo Structure

```
backend/           # FastAPI + Gemma 4 evaluation server (port 8092)
web/               # Angular 21 frontend — scenarios, audit chain, policy editor
policies/          # YAML policy definitions (clinical, security, lingua)
sdk/               # Python SDK — ToolGuard + AuditChain classes
verifier/          # Offline audit-chain tamper-detection CLI
notebook/          # Jupyter notebook — self-contained Gemma 4 walkthrough
tests/             # 14 pytest tests (unit + integration + audit-chain tamper detection)
```

---

## Quick Start

One command brings up Ollama, pulls `gemma4:e4b`, builds the Angular dashboard, and starts the FastAPI backend serving both the API and the UI:

```bash
git clone https://github.com/dimaggi-ai/health-tool-guard.git
cd health-tool-guard
docker compose -f docker/compose.yml up
```

Then open **[http://localhost:8080](http://localhost:8080)**.

First start takes ~5 min (3 GB model pull + npm install + build). Subsequent starts are <30 s — the model is cached in a named volume.

**Requirements:** Docker 24+, NVIDIA GPU with `nvidia-container-toolkit` for the warm-latency numbers above (~10 GB VRAM). Without a GPU, deterministic policies, audit chain, and scripted scenarios still run; HYBRID Gemma 4 calls fall back to CPU at <2 tok/s — usable for the demo but far slower than the warm-latency table. See [SETUP.md](SETUP.md) for native (non-Docker) install.

### Verify the audit chain

```bash
python verifier/verify.py verify --chain audit.jsonl
# → ✓ CHAIN VALID  (all hashes link; all content hashes match)
```

Tamper-detection demo: edit any byte in `audit.jsonl` → re-run → `✗ TAMPERED at record N`.

---

## Live Demo

**Submission demo (frontend-only, scripted scenarios):**
**[https://dimaggi.ai/health-tool-guard/](https://dimaggi.ai/health-tool-guard/)**

The submission demo at `/health-tool-guard/` runs the frontend with **scripted-fallback decisions**. The policy logic, decision outcomes, SHA-256 hashing, HMAC signing, and audit-chain linkage are all real and runnable — but the model inference is pre-recorded latency + token counts (the dashboard shows a *"Demo Mode — scripted scenarios"* banner at the top so this is unambiguous).

The ▶ Demo tab has two scenarios:
- **Luganda · Audio + Aspirin Allergy** — 1-click run; multilingual translation → DENY contraindication → SHA-256 audit
- **Acholi · Unsupported Language → Human** — 1-click run; ESCALATE in 8 ms → clinician routing → audit

**For live Gemma 4 inference + real openFDA fetches**, follow the [Quick Start](#quick-start). The same scenarios then call a real `gemma4:e4b` via Ollama and fetch live drug labels from `api.fda.gov`.

---

## Tests & Notebook

**14 pytest tests, <0.1 s total** — including audit-chain tamper detection (build a real chain, mutate a byte, verifier flags the corruption). Run inside the bundled container with:

```bash
docker compose -f docker/compose.yml exec -w /app app pytest tests/test_policies.py -v
```

An end-to-end Kaggle-runnable walkthrough is in [`notebook/tool-guard-gemma4.ipynb`](notebook/tool-guard-gemma4.ipynb).

---

## Limitations

Honest framing of what Tool Guard does **not** do today:

- **Policy surface is the tool call, not the transcript.** STT is out of scope — `/transcribe` provides translation context for the dashboard, while the real work runs on the resulting tool-call structure. A Whisper pre-stage or a future Gemma 4 audio variant plugs in without changing the policy layer.
- **Agent-layer prompt injection.** Tool Guard inspects the call, not the agent's system prompt — upstream poisoning is out of scope (Tool Guard still blocks the resulting unsafe call, but cannot detect the manipulation).
- **Non-FDA jurisdictions.** Hybrid contraindication checks pull openFDA labels; for EMA/MHRA/PMDA/NAFDAC the live grounding step is a no-op and the policy falls back to Gemma 4's pre-trained knowledge.
- **Low-resource languages.** Only 10 languages are certified for deterministic ALLOW; the rest fall under script-guard heuristics or route to ESCALATE. **This is the demo's escalation case, not a polished feature.**
- **Production key management.** The audit-chain HMAC secret is operator-managed; HSM/KMS rotation and authority-chain escrow are out of scope for the submission.
- **Single-tenant.** One global policy set and one audit chain. Multi-tenant isolation is roadmap, not submission.
- **Hybrid latency ceiling.** ~700–900 ms warm. Sub-100 ms agent loops must rely on the deterministic layer alone until the hybrid layer is batched or distilled.

---

## Ethical Considerations

- **No autonomous clinical action.** Tool Guard never *recommends* care. It only *intercepts and blocks* unsafe recommendations from an upstream agent. The patient-facing care decisions stay with the upstream system or, on ESCALATE, with a human clinician.
- **Patient data minimisation.** The PII-boundary policy redacts identifiers before any external transmission. The audit chain stores decision metadata and hashes, not raw patient records.
- **No model-driven discrimination.** Tool Guard uses a categorical certified-language set, not a continuous "model confidence" gauge that could systematically under-serve speakers of marginalised languages. When a language is not certified, the system escalates — it does not silently degrade.
- **Audit trail is for accountability, not surveillance.** Records are HMAC-signed and chained so that an operator can prove what was decided when. The chain does not store the patient's identity beyond what was passed in the tool call, and the HMAC secret can be rotated to invalidate forwards-derived attacks.

---

## Acknowledgements

This project is built with [**Google's Gemma 4**](https://ai.google.dev/gemma) open-weights model (E4B), used under the [**Gemma Terms of Use**](https://ai.google.dev/gemma/terms). Clinical drug-label grounding uses live data from the U.S. FDA's [openFDA API](https://open.fda.gov/) (public domain). Clinical references are drawn from peer-reviewed literature on PubMed Central (PMC IDs cited inline in the source).

The submission **video voiceover was generated with Gemini's free text-to-speech** in [Google AI Studio](https://aistudio.google.com/generate-speech) — Gacrux voice for the English narration, Leda for the Spanish patient line — no third-party narrator service.

**Dev tooling.** [Gemini CLI](https://github.com/google-gemini/gemini-cli) (Gemini 3.1 Pro) was used for code- and business-review passes; the same model plus local Gemma 4 E4B back DIMAGGI's internal CTO agent (draft-only, no autonomous actions). All AI-assisted outputs were reviewed and approved before commit.

Submitted for the [**Kaggle × Google DeepMind Gemma 4 Good Hackathon**](https://www.kaggle.com/competitions/gemma-4-good-hackathon) — Safety & Trust track.

---

## License

**Dual-licensed.** Pick whichever fits your use case:

1. **AGPL-3.0-or-later** *(default)* — free for research, internal evaluation, academic work, and any deployment willing to publish its full source under the same terms. See [LICENSE](LICENSE).
   - **Network use is distribution.** If you run a modified Tool Guard as a service (SaaS, internal portal, embedded product), AGPL §13 requires you to make the complete corresponding source of your version available to every user of that service.
2. **Commercial license** — for companies that want to ship Tool Guard inside a closed-source product or hosted service without the AGPL §13 source-disclosure obligation. Contact **founders@dimaggi.ai**.

The **DIMAGGI** and **Tool Guard** names, logos, and trade dress are reserved trademarks of DIMAGGI Inc. and are not licensed by AGPL-3.0 — forks must rename. See [NOTICE](NOTICE) for the full trademark + third-party attribution block.

Copyright © 2026 DIMAGGI Inc.
