"""
ToolGuard SDK — deterministic + hybrid policy evaluation for AI agent tool calls.

Usage:
    from toolguard import ToolGuard, AuditChain

    guard = ToolGuard(policies=[...])
    result = guard.evaluate("classify_symptoms", params={...}, agent_context={...})
    print(result.decision, result.latency_ms)
"""

from __future__ import annotations

import hashlib
import hmac as hmac_lib
import json
import os
import secrets
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# EvalResult
# ---------------------------------------------------------------------------

@dataclass
class EvalResult:
    decision: str                          # ALLOW | DENY | ESCALATE | FLAG | REDACT
    eval_path: str                         # deterministic | hybrid
    policy_triggered: Optional[str]        # policy name that fired, or None
    latency_ms: float                      # wall-clock ms for evaluation
    explanation: str                       # human-readable reason
    reasoning: str                         # structured reasoning trace
    hmac: str                              # HMAC-SHA256 of canonical fields
    hash: str                              # SHA-256 of this record
    prev_hash: str                         # hash of the previous record in chain
    nonce: str                             # 16-byte random hex nonce
    timestamp: float                       # Unix epoch (seconds, float)
    modality: str = "tool_call"            # extensible: tool_call | message | file_op
    # Source fields stored for offline HMAC re-derivation by the verifier
    tool: str = ""
    params: dict = field(default_factory=dict)
    agent_context: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# AuditChain
# ---------------------------------------------------------------------------

class AuditChain:
    """Immutable append-only SHA-256 hash-chained audit log."""

    GENESIS_HASH = "0" * 64

    def __init__(self) -> None:
        self._records: list[EvalResult] = []

    def add(self, result: EvalResult) -> None:
        self._records.append(result)

    def verify(self) -> bool:
        """Return True if every record's prev_hash equals the previous record's hash."""
        prev = self.GENESIS_HASH
        for i, r in enumerate(self._records):
            if r.prev_hash != prev:
                return False
            prev = r.hash
        return True

    def to_jsonl(self) -> str:
        """Serialise the chain to newline-delimited JSON."""
        lines = []
        for r in self._records:
            lines.append(json.dumps(asdict(r)))
        return "\n".join(lines)

    def __len__(self) -> int:
        return len(self._records)


# ---------------------------------------------------------------------------
# ToolGuard
# ---------------------------------------------------------------------------

# Tools that are allowed by the clinical-scope-lock policy
_CLINICAL_ALLOWED_TOOLS = {
    "classify_symptoms",
    "assess_urgency",
    "recommend_care_pathway",
    "generate_triage_summary",
    "send_referral_summary",
}

# PII field names that trigger pii-boundary
_PII_FIELDS = {"patient_name", "dob", "id_number", "mrn", "address"}

# Confidence threshold for confidence-gate
_CONFIDENCE_THRESHOLD = 0.70


def _detect_language(text: str) -> Optional[str]:
    """Detect language code using langdetect if available, else return None."""
    try:
        from langdetect import detect
        return detect(text)
    except Exception:
        return None


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


def _hmac_sign(secret: str, payload: str) -> str:
    return hmac_lib.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def _canonical(tool: str, params: dict, agent_context: dict, timestamp: float, nonce: str) -> str:
    """Deterministic canonical string for signing."""
    return json.dumps(
        {
            "tool": tool,
            "params": params,
            "agent_context": agent_context,
            "timestamp": timestamp,
            "nonce": nonce,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


class ToolGuard:
    """
    Policy engine for AI agent tool calls.

    Parameters
    ----------
    policies:
        List of policy dicts (e.g. loaded from YAML). Pass an empty list to
        use built-in defaults only.
    hmac_secret:
        Shared secret for HMAC signing of audit records.
    """

    def __init__(
        self,
        policies: list[dict] | None = None,
        hmac_secret: str = "toolguard-demo-2026",
    ) -> None:
        self._policies: list[dict] = policies or []
        self._secret = hmac_secret
        self._prev_hash = AuditChain.GENESIS_HASH
        self._hybrid_fn: Optional[Callable[[str, dict, dict, str], tuple[str, str]]] = None

    def set_hybrid_fn(
        self,
        fn: Callable[[str, dict, dict, str], tuple[str, str]],
    ) -> None:
        """
        Plug in an LLM for hybrid evaluation.

        The callable receives (tool, params, agent_context, policy_name) and
        must return (decision, reasoning) where decision is one of the standard
        decision strings.
        """
        self._hybrid_fn = fn

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        tool: str,
        params: dict,
        agent_context: dict | None = None,
    ) -> EvalResult:
        """
        Evaluate a tool call against all loaded policies.

        Deterministic rules are checked first (fast path).  If the triggered
        policy requires hybrid evaluation and a hybrid_fn is registered, it is
        called for the final decision.

        Returns an EvalResult that is ready to be appended to an AuditChain.
        """
        agent_context = agent_context or {}
        t0 = time.perf_counter()

        decision, eval_path, policy_name, explanation, reasoning = self._run_deterministic(
            tool, params, agent_context
        )

        # If deterministic said ALLOW and there are hybrid-only policies, run them
        if decision == "ALLOW":
            decision, eval_path, policy_name, explanation, reasoning = self._run_hybrid_policies(
                tool, params, agent_context
            )

        latency_ms = (time.perf_counter() - t0) * 1000

        timestamp = time.time()
        nonce = secrets.token_hex(16)
        canonical = _canonical(tool, params, agent_context, timestamp, nonce)
        sig = _hmac_sign(self._secret, canonical)
        record_hash = _sha256(canonical + sig)

        result = EvalResult(
            decision=decision,
            eval_path=eval_path,
            policy_triggered=policy_name,
            latency_ms=round(latency_ms, 3),
            explanation=explanation,
            reasoning=reasoning,
            hmac=sig,
            hash=record_hash,
            prev_hash=self._prev_hash,
            nonce=nonce,
            timestamp=timestamp,
            modality="tool_call",
            tool=tool,
            params=params,
            agent_context=agent_context,
        )
        self._prev_hash = record_hash
        return result

    # ------------------------------------------------------------------
    # Deterministic rule implementations
    # ------------------------------------------------------------------

    def _run_deterministic(
        self,
        tool: str,
        params: dict,
        agent_context: dict,
    ) -> tuple[str, str, Optional[str], str, str]:
        """
        Returns (decision, eval_path, policy_name, explanation, reasoning).
        eval_path is always "deterministic" here.
        """

        # 1. Rate governor (highest priority — security)
        rate_result = self._check_rate_governor(agent_context)
        if rate_result:
            return rate_result

        # 2. Exfiltration guard (security)
        exfil_result = self._check_exfiltration_guard(params, agent_context)
        if exfil_result:
            return exfil_result

        # 3. Lingua language match (highest lingua priority)
        lingua_result = self._check_lingua_language_match(tool, params, agent_context)
        if lingua_result:
            return lingua_result

        # 4. Lingua script guard
        script_result = self._check_lingua_script_guard(params, agent_context)
        if script_result:
            return script_result

        # 5. Clinical scope lock
        scope_result = self._check_scope_lock(tool)
        if scope_result:
            return scope_result

        # 6. PII boundary
        pii_result = self._check_pii_boundary(tool, params, agent_context)
        if pii_result:
            return pii_result

        # 7. Confidence gate
        confidence_result = self._check_confidence_gate(params, agent_context)
        if confidence_result:
            return confidence_result

        return (
            "ALLOW",
            "deterministic",
            None,
            "No deterministic policy triggered.",
            "All deterministic rules passed.",
        )

    def _check_rate_governor(
        self, agent_context: dict
    ) -> Optional[tuple[str, str, str, str, str]]:
        calls = int(agent_context.get("calls_in_window", 0))
        limit = 100
        if calls > limit:
            return (
                "DENY",
                "deterministic",
                "rate-governor",
                f"Rate limit exceeded: {calls} calls in 60s window.",
                f"agent.calls_in_window={calls} > max_calls_per_window={limit}",
            )
        return None

    def _check_exfiltration_guard(
        self, params: dict, agent_context: dict
    ) -> Optional[tuple[str, str, str, str, str]]:
        dest = agent_context.get("destination", {})
        is_external = dest.get("is_external", False) if isinstance(dest, dict) else False
        size = int(params.get("payload_size_bytes", 0))
        max_bytes = 10240
        if is_external and size > max_bytes:
            return (
                "DENY",
                "deterministic",
                "exfiltration-guard",
                f"Payload size {size} exceeds exfiltration limit {max_bytes} for external destination.",
                f"destination.is_external=True AND payload.size_bytes={size} > {max_bytes}",
            )
        return None

    def _check_lingua_language_match(
        self, tool: str, params: dict, agent_context: dict
    ) -> Optional[tuple[str, str, str, str, str]]:
        input_lang = agent_context.get("input_language")
        output_lang = params.get("output_language") or agent_context.get("output_language")

        if not input_lang or not output_lang:
            # Try auto-detection if raw text is provided
            input_text = agent_context.get("input_text", "")
            if input_text and not input_lang:
                input_lang = _detect_language(input_text)

        if input_lang and output_lang and input_lang != output_lang:
            return (
                "DENY",
                "deterministic",
                "lingua-language-match",
                f"Output language '{output_lang}' does not match input language '{input_lang}'.",
                f"input_language={input_lang} != output_language={output_lang}",
            )
        return None

    def _check_lingua_script_guard(
        self, params: dict, agent_context: dict
    ) -> Optional[tuple[str, str, str, str, str]]:
        script = agent_context.get("script") or params.get("script")
        supported = {"Latin", "Devanagari", "Arabic", "Bengali", "Ethiopic"}
        if script and script not in supported:
            return (
                "FLAG",
                "deterministic",
                "lingua-script-guard",
                f"Script '{script}' is not in the supported set; escalating for human review.",
                f"script={script} not in {sorted(supported)}",
            )
        return None

    def _check_scope_lock(
        self, tool: str
    ) -> Optional[tuple[str, str, str, str, str]]:
        if tool not in _CLINICAL_ALLOWED_TOOLS:
            return (
                "DENY",
                "deterministic",
                "clinical-scope-lock",
                f"Agent attempted '{tool}', outside validated triage scope.",
                f"tool_name='{tool}' not_in allowed_tools={sorted(_CLINICAL_ALLOWED_TOOLS)}",
            )
        return None

    def _check_pii_boundary(
        self, tool: str, params: dict, agent_context: dict
    ) -> Optional[tuple[str, str, str, str, str]]:
        dest = agent_context.get("destination", {})
        is_external = dest.get("is_external", False) if isinstance(dest, dict) else (
            agent_context.get("destination") == "external_api"
        )
        # Also check if destination is explicitly set as a string
        if not is_external:
            dest_str = agent_context.get("destination", "")
            if isinstance(dest_str, str) and "external" in dest_str.lower():
                is_external = True

        found_pii = _PII_FIELDS.intersection(params.keys())
        if is_external and found_pii:
            return (
                "REDACT",
                "deterministic",
                "pii-boundary",
                f"PHI fields {sorted(found_pii)} detected in external transmission; redacting.",
                f"destination.is_external=True AND pii_fields={sorted(found_pii)} present in params",
            )
        return None

    def _check_confidence_gate(
        self, params: dict, agent_context: dict
    ) -> Optional[tuple[str, str, str, str, str]]:
        raw = params.get("confidence") or agent_context.get("confidence")
        if raw is None:
            return None
        try:
            confidence = float(raw)
        except (TypeError, ValueError):
            return None
        if confidence < _CONFIDENCE_THRESHOLD:
            return (
                "ESCALATE",
                "deterministic",
                "confidence-gate",
                f"Confidence {confidence:.2f} below threshold {_CONFIDENCE_THRESHOLD}. Human review required.",
                f"agent.confidence={confidence} < {_CONFIDENCE_THRESHOLD}",
            )
        return None

    # ------------------------------------------------------------------
    # Hybrid policy routing
    # ------------------------------------------------------------------

    def _run_hybrid_policies(
        self,
        tool: str,
        params: dict,
        agent_context: dict,
    ) -> tuple[str, str, Optional[str], str, str]:
        """Route hybrid-only policies (contraindication-check, etc.) to the LLM fn."""
        hybrid_policies = [
            p for p in self._policies
            if isinstance(p, dict)
            and p.get("policy", {}).get("evaluation_path") == "hybrid"
        ]
        if not hybrid_policies or self._hybrid_fn is None:
            return (
                "ALLOW",
                "deterministic",
                None,
                "No hybrid policy triggered (no hybrid_fn registered).",
                "Hybrid policies skipped — no hybrid_fn set.",
            )

        for policy_entry in hybrid_policies:
            policy = policy_entry.get("policy", policy_entry)
            policy_name = policy.get("name", "unknown")
            decision, reasoning = self._hybrid_fn(tool, params, agent_context, policy_name)
            if decision != "ALLOW":
                return (
                    decision,
                    "hybrid",
                    policy_name,
                    f"Hybrid evaluation by {policy_name}: {decision}",
                    reasoning,
                )

        return (
            "ALLOW",
            "hybrid",
            None,
            "All hybrid policies passed.",
            "LLM evaluation returned ALLOW for all hybrid policies.",
        )


# ---------------------------------------------------------------------------
# Example usage
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import yaml  # pip install pyyaml

    policy_dir = os.path.join(os.path.dirname(__file__), "..", "policies")
    policies = []
    if os.path.isdir(policy_dir):
        for fname in sorted(os.listdir(policy_dir)):
            if fname.endswith(".yaml"):
                with open(os.path.join(policy_dir, fname)) as f:
                    policies.append(yaml.safe_load(f))

    guard = ToolGuard(policies=policies)
    chain = AuditChain()

    # --- Example 1: allowed tool ---
    r1 = guard.evaluate(
        "classify_symptoms",
        params={"symptoms": "chest pain", "output_language": "en"},
        agent_context={"input_language": "en", "confidence": 0.92},
    )
    chain.add(r1)
    print(f"[1] {r1.decision:10s}  policy={r1.policy_triggered}  latency={r1.latency_ms:.1f}ms")

    # --- Example 2: out-of-scope tool ---
    r2 = guard.evaluate(
        "prescribe_medication",
        params={"drug": "ibuprofen"},
        agent_context={"confidence": 0.95},
    )
    chain.add(r2)
    print(f"[2] {r2.decision:10s}  policy={r2.policy_triggered}  latency={r2.latency_ms:.1f}ms")

    # --- Example 3: low confidence ---
    r3 = guard.evaluate(
        "assess_urgency",
        params={"confidence": "0.51"},
        agent_context={},
    )
    chain.add(r3)
    print(f"[3] {r3.decision:10s}  policy={r3.policy_triggered}  latency={r3.latency_ms:.1f}ms")

    # --- Example 4: PII on external destination ---
    r4 = guard.evaluate(
        "send_referral_summary",
        params={"patient_name": "A.W.", "dob": "1980-01-01", "summary": "..."},
        agent_context={"destination": {"is_external": True}},
    )
    chain.add(r4)
    print(f"[4] {r4.decision:10s}  policy={r4.policy_triggered}  latency={r4.latency_ms:.1f}ms")

    # --- Verify chain integrity ---
    ok = chain.verify()
    print(f"\nAudit chain ({len(chain)} records): {'INTACT' if ok else 'BROKEN'}")

    # --- Dump JSONL ---
    jsonl = chain.to_jsonl()
    audit_path = "/tmp/toolguard_demo.jsonl"
    with open(audit_path, "w") as f:
        f.write(jsonl)
    print(f"Wrote audit log to {audit_path}")
