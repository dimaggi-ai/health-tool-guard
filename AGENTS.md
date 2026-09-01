# AI Development Agents

This document describes the AI-assisted development workflow used to build Tool Guard.

## Development Approach

Tool Guard was built using a multi-agent AI development workflow. Different specialised agents handled different aspects of the codebase:

- **Policy engine** — deterministic rule evaluation, YAML schema design, condition trees
- **Hybrid evaluator** — Gemma 4 E4B integration, prompt engineering, latency optimisation
- **Audit chain** — SHA-256 hash chaining implementation (Python + Web Crypto API)
- **Angular dashboard** — standalone components, signals, real-time decision feed
- **Multilingual enforcement** — Unicode script detection, language matching, 8-language test coverage
- **QA validation** — 78-check submission validator, policy coverage analysis

## Agent Roles

### Spec & Architecture Agent
Translated the 10-policy specification into implementable interfaces. Defined the `PolicyResult`, `DecisionTrace`, and `AuditEntry` data models shared across Python backend and TypeScript frontend.

### Implementation Agent
Wrote the core enforcement logic: `eval_deterministic()`, `eval_hybrid()`, and the Gemma 4 inference integration. Responsible for the <12ms deterministic and <800ms hybrid latency targets.

### QA Agent
Reviewed each implementation pass against the original spec. Generated `qa_validate.py` with 78 checks covering policy completeness, documentation accuracy, UI functionality, and audit chain integrity.

### Review Agent
Performed two-pass code review (independent of the implementation agent) to catch inconsistencies between documented and implemented behaviour. Identified the three YAML-only policies as undocumented gaps.

## What Was Not AI-Generated

- Product strategy and clinical use-case selection (DIMAGGI team)
- Policy design decisions (which 10 policies, what thresholds, what languages)
- FDA / EU AI Act regulatory framing
- Demo scenario content, patient vignettes, and clinical context

## Verification

All AI-generated code was reviewed, tested, and validated by the DIMAGGI engineering team before submission. The `qa_validate.py` script serves as the automated record of what was verified.

---

## Operational CTO Tooling (post-submission)

> The sections above describe the **hackathon submission** (frozen). The sections below describe **operational tooling** the DIMAGGI team uses internally to plan and steer the company. None of this ships in the submitted Tool Guard artifact at `dimaggi.ai/health-tool-guard/`.

### Three surfaces, one direction document

The current strategic direction lives in a single Markdown file:

```
~/workspace/dimaggi/demo/portal/cto/current.md
```

Three independent surfaces read or write that file:

| Surface | Where | What it does |
|---|---|---|
| **CTO Direction tab** *(web)* | `https://cacheos.tail39e3e5.ts.net/cto/` → 🧭 Direction (Caddy + passkey gate) | Generates / refines / saves the one-pager. Uses the local CTO agent's RAG store + your choice of model (Codex / Gemini / Claude / Gemma-local). |
| **Pre-prod portal one-pager** *(web)* | `http://192.168.4.35/cto/` (no auth — LAN/Tailscale) | Read-only rendered view of the current `current.md` for sharing inside the team. Updated by `make push-website`. |
| **cportal `cto` tab** *(terminal)* | `cportal` → press `7` (or Tab to it) | Read-only Rich-Markdown rendering of `current.md` in the terminal. Keys: `r` refresh · `o` open in `$EDITOR` · `w` open the web Direction tab. |

### Direction tab — generation flow

1. Pick a model (the choice persists in `localStorage`):
   - **Codex** — deepest design, 4-8 min, best for architecture and MVP scoping
   - **Gemini** — web research + fresh market data, 2-5 min, rate-limited some days
   - **Claude** — via `CLAUDE_CMD`, 1-3 min, balanced reasoning
   - **Gemma-local** — Ollama `gemma4:e4b`, 30-90 s, fully offline / air-gap capable
2. Type a topic ("What killer feature does Tool Guard need on top of MCP proxy + audit chain to be sellable to a 200-engineer org in May 2026?").
3. Click **Generate** — the backend:
   - Pulls top-12 RAG hits from the last 60 days via `rag.search()`
   - Builds a prompt with company context + RAG context + DRAFT-only safety rule + format spec (TL;DR, H2/H3, `[verified]`/`[plausible]`/`[unverified]` tags, decision questions, 600-1200 words)
   - Runs the chosen tool as a subprocess; returns Markdown
4. Refine via the chat input below the output ("shorter exec summary" / "add Vanta pricing"). Multi-turn; the latest doc is what gets saved.
5. Click **💾 Save as Current Direction** — writes to:
   - `demo/portal/cto/current.md` (the one-pager)
   - `cto-agent/reports/directions/direction-<timestamp>.md` (versioned archive)
6. Run `make push-website` from the dimaggi root to publish to `192.168.4.35/cto/`.

### Backend endpoints (in `cto-agent/server.py`)

- `POST /api/direction/generate` — body `{topic, tool}` → `{markdown, tool, rag_docs}`
- `POST /api/direction/refine` — body `{previous, message, tool}` → `{markdown, tool}`
- `POST /api/direction/save` — body `{markdown}` → `{saved_to, archive, next_step}`

The tool runner (`_dir_run_tool`) uses `_resolve_bin()` to discover each binary's path, because the systemd-user `dimaggi-cto-server.service` runs with a reduced `PATH` that excludes `~/.local/bin`. Falls back to known-location lists if `shutil.which()` fails.

### cportal cto tab — terminal viewer

`~/tools/cportal.py` gained a 7th tab. Reads `~/workspace/dimaggi/demo/portal/cto/current.md` and renders via `rich.markdown.Markdown`. No auth (terminal is local). Keys:

| Key | Action |
|---|---|
| `7` | Switch to cto tab |
| `r` | Refresh (re-read file) |
| `o` | Open the markdown file in `$EDITOR` (`xdg-open` if unset) |
| `w` | Open the web Direction tab (`xdg-open https://cacheos.tail39e3e5.ts.net/cto/`) |
| `q` | Quit cportal |

### Memory rules referenced from this tooling

- **Tool Guard prod freeze** — `/health-tool-guard/` on `dimaggi.ai` stays at the submission build for ~6 months. None of the operational tooling above touches that path.
- **Deploy dialog stays honest** — the deploy confirmation on `192.168.4.35/` is kept in sync with whatever `scripts/deploy.sh` actually does. The `current.md` displayed at `192.168.4.35/cto/` is preserved by every push.
- **CTO agent draft-only** — every direction generation includes the DRAFT-ONLY safety rule. The agent never sends emails, opens PRs, or takes any public action — outputs are drafts for human approval.

## CTO content — single source of truth (locked 2026-05-22)

The CTO direction one-pager appeared in three different versions: Caddy `/cto/`, the pre-prod CEO portal at `192.168.4.35/cto/`, and cportal. This rule removes that drift.

**Canonical location:** `~/workspace/dimaggi/cto-agent/reports/current.md`

**Who writes:** the `cto-agent` service AND the CTO/AI agent in this workspace. **Nobody else writes the file** — every other surface is a read-only sync target.

**Sync mechanism:** `~/workspace/dimaggi/cto-agent/sync.sh` propagates canonical to:
- `~/workspace/dimaggi/demo/portal/cto/current.md` — the file rsync'd to `192.168.4.35/cto/` by `make push-website` (the CEO portal). This file is stamped GENERATED at the top and must not be hand-edited.

**Hooks:**
- `make push-website` (root Makefile) invokes `sync.sh` before building the website. So pushing to pre-prod always carries the freshest canonical.
- `cportal` reads canonical directly (`~/workspace/dimaggi/cto-agent/reports/current.md`). The fallback path to `demo/portal/cto/current.md` was removed in the 2026-05-22 rebuild — no more split-brain.
- Caddy `/cto/` is already serving canonical via the `cto-agent` Python service on `127.0.0.1:9093`.

### Rule for the CTO/AI agent (this means YOU, future Claude session)

1. **Edit only `~/workspace/dimaggi/cto-agent/reports/current.md`.** Treat every other location as derived.
2. If you find yourself opening `~/workspace/dimaggi/demo/portal/cto/current.md` in `Read`/`Edit`, **stop**. That file is generated. Edit the canonical, then run `bash ~/workspace/dimaggi/cto-agent/sync.sh`.
3. The canonical file is markdown; ASCII-only by default. The sync script preserves bytes.
4. Major edits (full rewrites, restructuring) — back up with a timestamped copy to `~/workspace/dimaggi/cto-agent/reports/archive/` first.

### Rule for the overnight job

If any automated job runs unattended and mutates CTO content (e.g., daily-summary script, news collector that updates the direction note):

1. Acquire `flock` on `~/workspace/dimaggi/cto-agent/reports/.lock` before reading the current canonical.
2. Write atomically via `current.md.tmp` + `os.rename()` (the existing `analyst.py` pattern is the reference).
3. Release the lock.
4. Run `bash ~/workspace/dimaggi/cto-agent/sync.sh` afterwards so the downstream copies catch up.
5. Log the write to `~/workspace/dimaggi/cto-agent/reports/audit-chain.jsonl` with timestamp + sha256 of the new content + brief reason.

**Known caveat (v2 work):** the cto-agent service's `POST /api/direction/save` does not yet acquire `flock` for a full read-modify-write cycle — only file-level atomic rename. Concurrent human + agent edits could race; Gemini's pre-impl review flagged this. The fix is to wrap `analyst.py`'s write path in `flock`; tracked for the next cto-agent change. Acceptable for v1 because writes are infrequent and explicit.

### How to verify the rule is being followed

```bash
# Drift check — exits 0 if all targets match canonical:
bash ~/workspace/dimaggi/cto-agent/sync.sh --check

# Force re-sync if drift detected:
bash ~/workspace/dimaggi/cto-agent/sync.sh
```

If you've just edited canonical, the next `make push-website` carries it to pre-prod automatically.


## Editorial quality gate (hard rule)

Reader-facing English prose MUST pass an editorial review before it is treated as final or publish-ready. This includes website and product copy, articles, release notes, announcements, README and documentation prose, UI onboarding/help/error text, narrative reports, and material rewrites.

Required sequence:

1. Draft from verified facts and keep the source meaning intact.
2. Edit for clarity, specificity, consistent terminology, and an appropriate tone.
3. Recheck every fact, number, quotation, product name, command, and link after editing.
4. In the handoff, report `Editorial review: passed — <files>` or `Editorial review: not applicable — code-only change`.

Reviewers MUST treat missing editorial-review evidence as blocking when changed prose is in scope.

Never invent metrics, quotations, customers, anecdotes, personal experience, or certainty during editing. Style may change; facts may not.

This gate does not apply to executable code, identifiers, machine-readable schemas or protocols, generated files, literal quotations, or legal/regulatory text that must remain exact. Code comments need technical clarity, not marketing treatment.

If editorial review cannot be completed, stop before merge, publish, or deploy and request review. Do not silently skip the gate.
