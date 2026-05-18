"""
ToolGuard policy tests — deterministic evaluation path only.

Run with:
    cd <repo-root>
    pytest tests/test_policies.py -v
"""

import sys
import os

# Make the sdk module importable regardless of install state
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "sdk"))

import pytest
from toolguard import ToolGuard, AuditChain

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def guard():
    """ToolGuard instance with no external policies — built-in rules only."""
    return ToolGuard(policies=[], hmac_secret="test-secret")


# ---------------------------------------------------------------------------
# 1. clinical-scope-lock: out-of-scope tool is DENIED
# ---------------------------------------------------------------------------

def test_scope_lock(guard):
    result = guard.evaluate(
        "prescribe_medication",
        params={"drug": "ibuprofen"},
        agent_context={"confidence": 0.95},
    )
    assert result.decision == "DENY", f"Expected DENY, got {result.decision}"
    assert result.policy_triggered == "clinical-scope-lock"
    assert result.eval_path == "deterministic"


# ---------------------------------------------------------------------------
# 2. clinical-scope-lock: allowed tool is NOT denied by scope lock
# ---------------------------------------------------------------------------

def test_scope_lock_allowed_tool(guard):
    result = guard.evaluate(
        "classify_symptoms",
        params={"symptoms": "headache", "output_language": "en"},
        agent_context={"input_language": "en", "confidence": 0.90},
    )
    # Should not be denied by scope-lock
    assert result.policy_triggered != "clinical-scope-lock", (
        f"classify_symptoms should not trigger scope-lock, but got policy={result.policy_triggered}"
    )
    assert result.decision in ("ALLOW", "ESCALATE", "REDACT", "FLAG"), (
        f"Unexpected decision {result.decision}"
    )


# ---------------------------------------------------------------------------
# 3. pii-boundary: PII on external destination → REDACT
# ---------------------------------------------------------------------------

def test_pii_boundary(guard):
    result = guard.evaluate(
        "send_referral_summary",
        params={
            "patient_name": "A.W.",
            "dob": "1980-04-12",
            "summary": "Chest pain, referred to cardiology",
        },
        agent_context={"destination": {"is_external": True}, "confidence": 0.95},
    )
    assert result.decision == "REDACT", f"Expected REDACT, got {result.decision}"
    assert result.policy_triggered == "pii-boundary"


# ---------------------------------------------------------------------------
# 4. pii-boundary: PII on INTERNAL destination → NOT triggered
# ---------------------------------------------------------------------------

def test_pii_internal_allowed(guard):
    result = guard.evaluate(
        "send_referral_summary",
        params={
            "patient_name": "A.W.",
            "dob": "1980-04-12",
            "summary": "Chest pain, referred to cardiology",
        },
        agent_context={
            "destination": {"is_external": False},
            "input_language": "en",
            "confidence": 0.95,
        },
    )
    assert result.policy_triggered != "pii-boundary", (
        f"Internal destination should not trigger pii-boundary; got policy={result.policy_triggered}"
    )


# ---------------------------------------------------------------------------
# 5. confidence-gate: low confidence → ESCALATE
# ---------------------------------------------------------------------------

def test_confidence_gate(guard):
    result = guard.evaluate(
        "assess_urgency",
        params={"confidence": "0.51"},
        agent_context={"input_language": "en"},
    )
    assert result.decision == "ESCALATE", f"Expected ESCALATE, got {result.decision}"
    assert result.policy_triggered == "confidence-gate"


# ---------------------------------------------------------------------------
# 6. confidence-gate: high confidence → NOT triggered
# ---------------------------------------------------------------------------

def test_confidence_above_threshold(guard):
    result = guard.evaluate(
        "assess_urgency",
        params={"confidence": "0.80"},
        agent_context={"input_language": "en"},
    )
    assert result.policy_triggered != "confidence-gate", (
        f"Confidence 0.80 should not trigger confidence-gate; got policy={result.policy_triggered}"
    )


# ---------------------------------------------------------------------------
# 7. lingua-language-match: output lang != input lang → DENY
# ---------------------------------------------------------------------------

def test_lingua_language_mismatch(guard):
    result = guard.evaluate(
        "generate_triage_summary",
        params={"output_language": "en", "summary": "Your triage result is normal."},
        agent_context={"input_language": "bn", "confidence": 0.90},
    )
    assert result.decision == "DENY", f"Expected DENY, got {result.decision}"
    assert result.policy_triggered == "lingua-language-match"


# ---------------------------------------------------------------------------
# 8. lingua-language-match: matching languages → NOT triggered
# ---------------------------------------------------------------------------

def test_lingua_english_allowed(guard):
    result = guard.evaluate(
        "generate_triage_summary",
        params={"output_language": "en", "summary": "Your triage result is normal."},
        agent_context={"input_language": "en", "confidence": 0.90},
    )
    assert result.policy_triggered != "lingua-language-match", (
        f"Matching languages should not trigger lingua-language-match; got policy={result.policy_triggered}"
    )
    assert result.decision not in ("DENY",) or result.policy_triggered != "lingua-language-match"


# ---------------------------------------------------------------------------
# 9. rate-governor: calls_in_window exceeds limit → DENY
# ---------------------------------------------------------------------------

def test_rate_governor_triggered(guard):
    result = guard.evaluate(
        "classify_symptoms",
        params={"symptoms": "fever"},
        agent_context={"calls_in_window": 150},
    )
    assert result.decision == "DENY", f"Expected DENY, got {result.decision}"
    assert result.policy_triggered == "rate-governor"


# ---------------------------------------------------------------------------
# 10. exfiltration-guard: large payload to external → DENY
# ---------------------------------------------------------------------------

def test_exfiltration_guard(guard):
    result = guard.evaluate(
        "send_referral_summary",
        params={"payload_size_bytes": 50000, "data": "x" * 100},
        agent_context={
            "destination": {"is_external": True},
            "confidence": 0.95,
            "input_language": "en",
        },
    )
    assert result.decision == "DENY", f"Expected DENY, got {result.decision}"
    assert result.policy_triggered == "exfiltration-guard"


# ---------------------------------------------------------------------------
# 11. AuditChain integrity: verify() returns True for clean chain
# ---------------------------------------------------------------------------

def test_audit_chain_integrity(guard):
    chain = AuditChain()
    tools = [
        ("classify_symptoms", {"output_language": "en"}, {"input_language": "en", "confidence": 0.91}),
        ("assess_urgency", {"confidence": "0.85"}, {"input_language": "en"}),
        ("recommend_care_pathway", {"output_language": "en"}, {"input_language": "en", "confidence": 0.88}),
    ]
    for tool, params, ctx in tools:
        r = guard.evaluate(tool, params, ctx)
        chain.add(r)

    assert chain.verify(), "Audit chain should be intact after sequential evaluate() calls"
    assert len(chain) == 3


# ---------------------------------------------------------------------------
# 12. AuditChain tamper detection: mutating a hash breaks verify()
# ---------------------------------------------------------------------------

def test_audit_chain_tamper_detection(guard):
    chain = AuditChain()
    r1 = guard.evaluate("classify_symptoms", {"output_language": "en"}, {"input_language": "en", "confidence": 0.90})
    r2 = guard.evaluate("assess_urgency", {"confidence": "0.85"}, {"input_language": "en"})
    chain.add(r1)
    chain.add(r2)

    assert chain.verify(), "Chain should be intact before tampering"

    # Tamper with the first record's hash
    chain._records[0].hash = "deadbeef" * 8
    assert not chain.verify(), "Chain should be BROKEN after hash tampering"


# ---------------------------------------------------------------------------
# 13. JSONL round-trip: serialise and count records
# ---------------------------------------------------------------------------

def test_audit_chain_jsonl(guard):
    import json

    chain = AuditChain()
    for _ in range(3):
        r = guard.evaluate("classify_symptoms", {"output_language": "en"}, {"input_language": "en", "confidence": 0.90})
        chain.add(r)

    jsonl = chain.to_jsonl()
    lines = [l for l in jsonl.splitlines() if l.strip()]
    assert len(lines) == 3

    for line in lines:
        record = json.loads(line)
        assert "decision" in record
        assert "hmac" in record
        assert "hash" in record
        assert "prev_hash" in record


# ── Integration test: verifier works on real JSONL ────────────────────────────

def test_verifier_on_real_chain():
    """Generate a 3-record chain via SDK and verify it passes the verifier."""
    import subprocess, sys, json, tempfile, os

    tg = ToolGuard(policies=[], hmac_secret="test-secret")

    records = []
    cases = [
        ("classify_symptoms",    {"symptoms": "fever", "language": "sw"}, {}, "sw"),
        ("recommend_care_pathway",{"recommendation": "ibuprofen", "patient_allergies": "aspirin"}, {}, "ar"),
        ("generate_triage_summary",{"summary": "stable", "output_language": "en"}, {}, "sw"),
    ]
    for i, (tool, params, ctx, lang) in enumerate(cases):
        r = tg.evaluate(tool, params, ctx)
        records.append(json.dumps({
            "tool": tool, "params": params, "agent_context": ctx,
            "decision": r.decision, "eval_path": r.eval_path,
            "policy_triggered": r.policy_triggered, "latency_ms": r.latency_ms,
            "explanation": r.explanation, "hmac": r.hmac,
            "hash": r.hash, "prevHash": r.prev_hash,
            "timestamp": r.timestamp, "language": lang,
            "nonce": f"nonce_{i}",  # marks as demo record — verifier checks chain linkage only
        }))

    with tempfile.NamedTemporaryFile(mode='w', suffix='.jsonl', delete=False) as f:
        f.write('\n'.join(records))
        path = f.name

    try:
        result = subprocess.run(
            [sys.executable, "verifier/verify.py", "verify", "--chain", path],
            capture_output=True, text=True
        )
        assert result.returncode == 0, f"Verifier failed:\n{result.stdout}\n{result.stderr}"
        assert "Chain intact" in result.stdout
    finally:
        os.unlink(path)
