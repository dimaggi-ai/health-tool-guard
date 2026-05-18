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
