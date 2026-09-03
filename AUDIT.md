# DIMAGGI Tool Guard — Audit Chain Specification

Every decision the Tool Guard proxy makes is recorded in a tamper-evident, cryptographically linked audit chain. This document describes the chain format, integrity rules, and how to verify a chain you have downloaded from the live demo or exported from your own deployment.

---

## What the Audit Chain Is

The audit chain is a sequence of JSON records written to a newline-delimited JSON file (`audit.jsonl`). Each record represents a single policy evaluation event — one tool call, one decision. Records are linked by a SHA-256 hash chain: each record's `prev_hash` field must equal the `hash` field of the preceding record. The chain also carries a per-record HMAC signature so that both linkage integrity and record authenticity can be verified independently.

The chain provides:

- **Tamper evidence** — modifying any record breaks the hash chain from that point forward, making alteration detectable without access to the original.
- **Non-repudiation** — the HMAC proves a specific operator key signed each record at write time.
- **Replay protection** — each record carries a cryptographic nonce, preventing an attacker from replaying old records in a forged chain.

---

## Record Format

Each line in `audit.jsonl` is a single JSON object with the following fields:

| Field | Type | Description |
|-------|------|-------------|
| `id` | string (UUID v4) | Unique record identifier. |
| `timestamp` | string (ISO 8601) | UTC time when the evaluation completed. |
| `agent` | string | Agent identifier (e.g. `medication-advisor`, `document-summarizer`). |
| `tool` | string | Name of the tool call being evaluated. |
| `decision` | string | Outcome: `ALLOW`, `DENY`, `REDACT`, `ESCALATE`, or `FLAG`. |
| `eval_path` | string | `deterministic` or `hybrid` — which evaluation tier made the decision. |
| `latency_ms` | integer | Wall-clock evaluation time in milliseconds. |
| `policy` | string | Policy ID that triggered the decision (e.g. `clinical-scope-lock`). |
| `explanation` | string | Human-readable reason for the decision. |
| `nonce` | string (hex, 32 bytes) | Cryptographic nonce; unique per record, prevents replay. |
| `modality` | string | Input modality: `text`, `tool_call`, `structured`. |
| `hmac` | string (hex) | HMAC-SHA256 of `(id \|\| decision \|\| latency_ms \|\| tool)` using the operator secret. |
| `hash` | string (hex) | SHA-256 of the full record JSON (with `hash` field set to empty string during computation). |
| `prev_hash` | string (hex) | `hash` of the immediately preceding record. Genesis record uses the sentinel below. |
| `scenario` | string | Optional scenario label for demo/notebook contexts. |
| `language` | string | BCP 47 language tag of the tool call context (e.g. `en`, `es`, `ar`). |

**Example record:**

```json
{
  "id": "a3f2c1d0-8b4e-4f7a-b9c2-1e5d3a7f0c8b",
  "timestamp": "2026-05-11T14:23:07.412Z",
  "agent": "medication-advisor",
  "tool": "prescribe_medication",
  "decision": "DENY",
  "eval_path": "hybrid",
  "latency_ms": 612,
  "policy": "contraindication-check",
  "explanation": "ibuprofen (NSAID) conflicts with documented NSAID allergy",
  "nonce": "4a8f3c2e1b7d9f0a2c5e8b1d4f7a3c6e",
  "modality": "tool_call",
  "hmac": "7f3a2b1c9d4e8f0a3c6b9e2d5f8a1c4e7b0d3f6a9c2e5b8d1f4a7c0e3b6d9f2",
  "hash": "9c4e2a7f1b5d8c3e6b0f4a9d2c7e1b5f8a3d6c0e4b7f2a5c9e1b4d7f0a3c6e9",
  "prev_hash": "3b6c9f2a5e8d1b4c7f0a3e6b9c2f5a8d1b4e7c0f3a6c9b2e5d8f1b4a7c0e3f6",
  "scenario": "clinical-demo",
  "language": "en"
}
```

---

## Chain Integrity Rule

Each record's `prev_hash` must equal the `hash` field of the immediately preceding record:

```
record[n].prev_hash == record[n-1].hash
```

This rule must hold for every consecutive pair of records. If any record's `prev_hash` does not match the previous record's `hash`, the chain is broken at that point — indicating insertion, deletion, or modification of records.

---

## HMAC Signature

The HMAC provides record-level authenticity independent of the chain linkage. It is computed as:

```
hmac = HMAC-SHA256(
  key   = operator_secret,
  msg   = id || decision || str(latency_ms) || tool
)
```

Where `||` denotes concatenation (no separator). The operator secret is the value of the `TOOLGUARD_SECRET` environment variable set at proxy startup. Verifying the HMAC confirms that a specific operator instance wrote the record — a different secret produces a different HMAC.

---

## Nonce

The `nonce` field holds a 32-byte (64 hex character) random value generated fresh for each record at write time. Because it participates in the hash computation, two records with identical content but different nonces yield distinct hashes. This stops replay attacks where an attacker copies a legitimate ALLOW record and inserts it to substitute for a DENY.

---

## Genesis Record

The first record in any chain has no predecessor. Its `prev_hash` is set to the fixed sentinel value:

```
sha256_0000000000000000000000000000000000000000000000000000000000genesis
```

Verifiers must accept this exact sentinel string as a valid `prev_hash` for the first record only.

---

## How to Verify

**Using the standalone verifier:**

```bash
python verifier/verify.py verify --chain audit.jsonl
```

**Using the CLI (after installing the SDK):**

```bash
pip install -e sdk/
toolguard verify --chain audit.jsonl
```

**With a specific operator secret (to validate HMACs):**

```bash
TOOLGUARD_SECRET=my-operator-secret toolguard verify --chain audit.jsonl
```

If `TOOLGUARD_SECRET` is not set, the verifier skips HMAC validation and only checks hash linkage.

---

## Downloading from the Live Demo

1. Open the live demo at https://dimaggi.com/demo-portal/ and log in.
2. Navigate to the **Audit Chain** page from the left sidebar.
3. Run any scenario (or use a previously completed one).
4. Click **Download audit.jsonl** in the top-right corner of the Audit Chain table.
5. Save the file and run `toolguard verify --chain audit.jsonl` locally.

---

## Interpreting Results

| Output | Meaning |
|--------|---------|
| `✓ Chain intact — no tampering detected` | All `prev_hash` values match their predecessors, genesis record is valid, and (if secret provided) all HMACs verify. The chain is trustworthy. |
| `✗ Chain BROKEN at record N` | Record N's `prev_hash` does not match record N-1's `hash`. Records have been inserted, deleted, or modified at or before position N. The chain cannot be trusted from that point forward. |
| `✗ HMAC mismatch at record N` | The HMAC on record N does not match what the provided secret produces. The record was written by a different operator instance, or the record content was altered after signing. |
| `✗ Duplicate nonce at record N` | Record N shares a nonce with an earlier record, indicating a replay or copy-paste forgery. |

The verifier exits with code `0` on success and `1` on any integrity failure, making it suitable for use in CI pipelines or automated compliance checks.
