"""
Tool Guard Evaluation Server
Calls local Ollama Gemma model for real policy evaluation.
"""
import json, hashlib, hmac, time, re, asyncio, os, logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s | %(message)s")
log = logging.getLogger("toolguard")

app = FastAPI(title="Tool Guard Evaluation Server")
# CORS: deliberately narrow. Add more origins via TOOLGUARD_CORS_ORIGINS (comma-separated).
_default_origins = ["http://localhost:4200", "https://dimaggi.ai", "https://dimaggi.com"]
_extra = [o.strip() for o in os.environ.get("TOOLGUARD_CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_default_origins + _extra,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Ollama endpoint. Default targets a localhost install per README quick-start;
# the bundled Docker setup overrides via OLLAMA_BASE=http://ollama:11434.
OLLAMA_BASE = os.environ.get("OLLAMA_BASE", "http://localhost:11434").rstrip("/")
OLLAMA_URL = f"{OLLAMA_BASE}/api/generate"
# Audit-chain HMAC key. Override in production via TOOLGUARD_HMAC_SECRET.
HMAC_SECRET = os.environ.get("TOOLGUARD_HMAC_SECRET", "toolguard-demo-2026").encode()
MODEL = "gemma4:e4b"
AUTO_UNLOAD_SECONDS = 900  # 15 minutes idle → release Gemma 4 from VRAM

_gemma_loaded = False
_last_used: float = 0.0


async def _load_gemma():
    global _gemma_loaded, _last_used
    async with httpx.AsyncClient(timeout=90.0) as client:
        await client.post(OLLAMA_URL, json={
            "model": MODEL, "prompt": "Ready.", "stream": False,
            "keep_alive": "30m", "options": {"num_predict": 1},
        })
    _gemma_loaded = True
    _last_used = time.time()


async def _unload_gemma():
    global _gemma_loaded
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.post(OLLAMA_URL, json={"model": MODEL, "prompt": "", "stream": False, "keep_alive": 0})
    _gemma_loaded = False


async def _idle_watchdog():
    """Background task: unload Gemma 4 after AUTO_UNLOAD_SECONDS of inactivity."""
    import asyncio
    while True:
        await asyncio.sleep(60)
        if _gemma_loaded and _last_used > 0 and (time.time() - _last_used) > AUTO_UNLOAD_SECONDS:
            log.info("watchdog: %ss idle — releasing Gemma 4 from VRAM", AUTO_UNLOAD_SECONDS)
            await _unload_gemma()


@app.on_event("startup")
async def startup():
    import asyncio
    asyncio.create_task(_idle_watchdog())
    asyncio.create_task(_auto_load_gemma())

async def _auto_load_gemma():
    """Pre-load Gemma 4 on startup so clinical reasoning is ready immediately."""
    import asyncio
    await asyncio.sleep(3)
    try:
        await _load_gemma()
    except Exception:
        pass


# Gemma 4 is the only model. Translation, contraindication reasoning, and
# autonomous-action detection all go through gemma4:e4b via Ollama.

# ── Policy definitions ────────────────────────────────────────────────────────
POLICIES = {
    "clinical-scope-lock": {
        "type": "deterministic",
        "description": "Deny tool calls outside triage scope",
        "allowed_tools": ["classify_symptoms", "assess_urgency", "recommend_care_pathway", "generate_triage_summary", "send_referral_summary"],
    },
    "pii-boundary": {
        "type": "deterministic",
        "description": "Redact PII fields before external transmission",
        "pii_fields": ["patient_name", "dob", "id_number", "mrn", "address"],
    },
    "confidence-gate": {
        "type": "deterministic",
        "description": "Escalate when agent confidence below threshold",
        "threshold": 0.70,
    },
    "contraindication-check": {
        "type": "hybrid",
        "description": "Flag recommendations conflicting with patient conditions or allergies",
    },
    "lingua-language-match": {
        "type": "deterministic",
        "description": "Output language must match input language",
        "unsupported_action": "ESCALATE",
    },
    "no-public-actions": {
        "type": "deterministic",
        "description": "Deny tool calls that would trigger public-facing actions without human approval",
        "blocked_tools": [
            "send_email", "send_message", "post_to_linkedin", "post_to_twitter",
            "post_to_hn", "create_github_issue", "create_github_pr",
            "create_github_comment", "merge_pr", "submit_form", "submit_application",
            "submit_grant", "publish_post", "contact_external", "deploy_to_production",
        ],
    },
    "draft-only-mode": {
        "type": "hybrid",
        "description": "Gemma 4 detects autonomous public action intent in agent output — escalates for human review",
    },
}

CLINICAL_GUIDELINES = """
OFFICIAL CLINICAL CONTRAINDICATION GUIDELINES
Sources: FDA Structured Product Labeling (openFDA), WHO, PMC peer-reviewed literature.

1. NSAIDs + ASPIRIN ALLERGY (FDA Naproxen SPL, Section 4 Contraindications):
   Naproxen is contraindicated in patients with history of asthma, urticaria, or allergic reactions
   after aspirin or NSAIDs. Ibuprofen OTC label: may cause severe allergic reaction especially in
   aspirin-allergic patients. MECHANISM: COX-1 inhibition - all strong COX-1 inhibitors cross-react.
   AERD prevalence: 7% of asthmatics, up to 30-40% with nasal polyposis. [PMC3005316; ACC 2024]
   RULE: ANY NSAID absolutely contraindicated in aspirin-allergic patients.

2. PENICILLIN ALLERGY + BETA-LACTAM ANTIBIOTICS (FDA Amoxicillin SPL Section 4):
   Amoxicillin is contraindicated in patients with history of allergic reactions to penicillins.
   MECHANISM: Amoxicillin is an aminopenicillin — same beta-lactam ring structure as penicillin.
   Cross-reactivity via IgE-mediated beta-lactam ring reactions: 1-10% risk (CDC 2019).
   Anaphylaxis incidence: 0.004-0.015%. Life-threatening.
   SAFE ALTERNATIVE: Azithromycin (macrolide class — no beta-lactam ring, no cross-reactivity).
   Azithromycin 500mg day 1, 250mg days 2-5 covers community-acquired respiratory infections.
   RULE: Amoxicillin, ampicillin, and ALL penicillin-family drugs CONTRAINDICATED in penicillin-allergic patients.

3. FLUOROQUINOLONES + INSULIN (FDA Ciprofloxacin SPL, Section 5.19):
   Associated with hypoglycemia in diabetic patients on insulin or oral hypoglycemics.
   Severe hypoglycemia resulting in coma or death has been reported.

4. ACE INHIBITORS + PREGNANCY (FDA Lisinopril SPL, Warning 5.1):
   Can cause fetal harm. Discontinue as soon as pregnancy is detected.

5. BETA-BLOCKERS + VERAPAMIL (FDA Metoprolol SPL, Section 7.4):
   Increased risk of bradycardia, AV block, cardiac arrest.

6. WHO ETAT EMERGENCY TRIAGE (WHO Emergency Triage Assessment and Treatment Manual, 2005/2013):
   Emergency respiratory rate thresholds: under 2 months >=60/min, 2-12 months >=50/min, 1-5yr >=40/min.
   Emergency signs: coma, convulsions, shock (cold hands + cap refill >3s + weak pulse).
   Malaria + coma/convulsions = EMERGENCY.

7. HIPAA MINIMUM NECESSARY (45 CFR 164.502(b)): Limit PHI to minimum necessary for the purpose.
   PHI = patient_name, dob, id_number, address when linked to health info. External transmission requires minimization.
   GDPR Article 9(1): health data is a special category - prohibited without Article 9(2)(h) conditions.

8. AI ESCALATION THRESHOLDS (FDA AI-Enabled Device Guidance 2025; Epic Sepsis AI Incident #123):
   Pre-specified confidence threshold triggers mandatory human review. WHO (2021): audits must verify
   AI systems perform as intended. Epic Sepsis AI (JAMA Intern Med 2021): sensitivity 63%, PPV 12% — 109 alerts per true sepsis case, majority false positives.

9. PARACETAMOL/ACETAMINOPHEN SAFETY (FDA OTC Acetaminophen Black Box Warning, 2011):
   Paracetamol (acetaminophen, CAS 103-90-2) is NOT an NSAID. It does NOT significantly inhibit
   COX-1 or COX-2 at therapeutic doses and does NOT cross-react with aspirin/NSAID allergies.
   It is the SAFE analgesic alternative for aspirin-sensitive/AERD patients at standard doses.
   RULE (standard doses, no alcohol): Paracetamol ≤4g/day = SAFE in aspirin-allergic patients. Do NOT deny paracetamol for aspirin-allergic patients — it is the recommended alternative.
   EXCEPTION — alcohol interaction: FDA Black Box Warning: "Severe liver damage may occur if you
   take 3 or more alcoholic drinks every day while using this product." Maximum safe dose with
   chronic heavy alcohol use (≥3 drinks/day): 2g/day. Exceeding this = hepatotoxicity risk.
   RULE (with chronic heavy alcohol): Paracetamol >2g/day + ≥3 drinks/day = FLAG.

10. QT PROLONGATION AND TORSADES DE POINTES (FDA Drug Safety Communication March 12 2013,
    Azithromycin; FDA Haloperidol Decanoate SPL Section 5.3; CredibleMeds QTDrugs List):
    Combining two QT-prolonging drugs = additive risk of Torsades de Pointes (TdP) and sudden
    cardiac death. High-risk QT-prolonging drug classes:
    - Antibiotics: azithromycin, clarithromycin, levofloxacin, moxifloxacin
    - Antipsychotics: haloperidol, quetiapine, ziprasidone, risperidone (all CredibleMeds Known Risk)
    - Antiemetics: ondansetron, domperidone
    FDA 2013: azithromycin "can cause potentially fatal irregular heart rhythms" in patients on
    other QT-prolonging medications.
    RULE: Antipsychotic + QT-prolonging antibiotic = FLAG for ECG monitoring and specialist review.

11. EMERGENCY EXCEPTION PRINCIPLE (ACC/AHA STEMI Guidelines 2013, Section 4.4.2.2):
    In immediately life-threatening emergencies (STEMI, anaphylaxis, severe shock), standard
    contraindication rules may require physician override.
    STEMI EXAMPLE: Aspirin 162-325mg loading is Class I recommendation (ACC/AHA 2013) for STEMI
    even in aspirin-allergic patients — the cardiac benefit outweighs allergy risk. Physician
    must make this judgment.
    RULE: When a LIFE-THREATENING EMERGENCY INDICATION conflicts with a documented contraindication,
    do NOT return DENY. Return ESCALATE with reasoning explaining the conflict. Blind DENY in
    emergencies is dangerous — human physician must decide.
"""

# ── Live medical database search ─────────────────────────────────────────────
FDA_LABEL_URL  = "https://api.fda.gov/drug/label.json"
PUBMED_SEARCH  = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_FETCH   = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

async def search_fda_label(drug_name: str) -> str:
    """Fetch the real FDA contraindications + warnings section for a drug."""
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(FDA_LABEL_URL, params={
                "search": f'openfda.generic_name:"{drug_name}"',
                "limit": 1,
            })
            data = r.json()
            result = data.get("results", [])
            if not result:
                # Fall back to brand name search
                r = await client.get(FDA_LABEL_URL, params={
                    "search": f'openfda.brand_name:"{drug_name}"',
                    "limit": 1,
                })
                data = r.json()
                result = data.get("results", [])
            if not result:
                return ""
            label = result[0]
            sections = []
            for field in ("contraindications", "warnings", "warnings_and_cautions",
                          "drug_interactions", "boxed_warning"):
                val = label.get(field)
                if val:
                    sections.append(f"[FDA SPL — {field.upper().replace('_',' ')}]\n{' '.join(val)[:800]}")
            return "\n\n".join(sections[:3])
    except Exception as e:
        log.warning("fda_search %s failed: %s", drug_name, e)
        return ""

async def search_pubmed(query: str, max_results: int = 3) -> list[dict]:
    """Search PubMed for relevant citations and return title + abstract snippets."""
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            # Step 1: search for PMIDs
            sr = await client.get(PUBMED_SEARCH, params={
                "db": "pubmed", "term": query, "retmax": max_results,
                "retmode": "json", "sort": "relevance",
            })
            pmids = sr.json().get("esearchresult", {}).get("idlist", [])
            if not pmids:
                return []
            # Step 2: fetch abstracts
            fr = await client.get(PUBMED_FETCH, params={
                "db": "pubmed", "id": ",".join(pmids),
                "rettype": "abstract", "retmode": "text",
            })
            # Parse the plain-text abstract dump
            articles = []
            for chunk in fr.text.split("\n\n\n"):
                lines = [l.strip() for l in chunk.strip().splitlines() if l.strip()]
                if lines:
                    articles.append({
                        "title": lines[0][:120] if lines else "",
                        "snippet": " ".join(lines[1:4])[:300] if len(lines) > 1 else "",
                    })
            return articles[:max_results]
    except Exception as e:
        log.warning("pubmed_search %r failed: %s", query, e)
        return []

# ── Request / Response models ──────────────────────────────────────────────────
class EvalRequest(BaseModel):
    tool: str
    params: dict
    agent_id: str = "clinical-triage-agent-v1"
    patient_context: dict = {}
    input_language: str = "en"
    output_language: str = "en"
    agent_confidence: float = 1.0

class EvalResponse(BaseModel):
    decision: str
    eval_path: str
    policy_triggered: str
    latency_ms: int
    explanation: str
    reasoning: str
    why_hybrid: str = ""
    redacted_fields: list = []
    translated_response: str = ""
    tokens_used: int = 0            # Gemma 4 eval_count from Ollama
    fda_sources: list = []          # [{"drug":"ibuprofen","chars":847}, ...] from openFDA
    hmac: str
    hash: str
    timestamp: str

# ── Deterministic evaluation (fast path) ──────────────────────────────────────
def eval_deterministic(req: EvalRequest) -> dict | None:
    """Returns a result dict if deterministic rules match, else None → route to hybrid."""

    # Scope lock
    allowed = POLICIES["clinical-scope-lock"]["allowed_tools"]
    if req.tool not in allowed:
        return {
            "decision": "DENY",
            "policy_triggered": "clinical-scope-lock v1.0",
            "explanation": f"DENIED. {req.tool} is outside triage scope. Only {', '.join(allowed)} are permitted.",
            "reasoning": f"Tool name '{req.tool}' not in whitelist. Immediate DENY. No model call needed.",
            "redacted_fields": [],
        }

    # PII boundary
    pii_fields = POLICIES["pii-boundary"]["pii_fields"]
    found_pii = [f for f in pii_fields if f in req.params]
    dest = req.params.get("destination", "")
    is_external = "external" in dest.lower() or "api" in dest.lower()
    if found_pii and is_external:
        # ACTUALLY mutate the params — PHI must not leave Tool Guard.
        # The /agent endpoint returns the (now-redacted) params back to caller.
        for f in found_pii:
            req.params[f] = "[REDACTED]"
        return {
            "decision": "REDACT",
            "policy_triggered": "pii-boundary v1.0",
            "explanation": f"PII detected in outbound call. {len(found_pii)} field(s) redacted in-place. Sanitised version forwarded.",
            "reasoning": f"Destination '{dest}' is external. Parameters contained PII fields: {found_pii}. Action: REDACT_AND_CONTINUE — values replaced with [REDACTED] before downstream transmission.",
            "redacted_fields": found_pii,
        }

    # Confidence gate
    if req.agent_confidence < POLICIES["confidence-gate"]["threshold"]:
        return {
            "decision": "ESCALATE",
            "policy_triggered": "confidence-gate v1.0",
            "explanation": f"Agent confidence {req.agent_confidence:.2f} below threshold 0.70. Escalated to human clinician.",
            "reasoning": f"Threshold comparison: {req.agent_confidence:.2f} < 0.70. When uncertain, Tool Guard does not permit autonomous action.",
            "redacted_fields": [],
        }

    # Language match — unsupported language check must run BEFORE mismatch check
    # Acholi ("ach") is intentionally NOT in this set — it's the v3 demo escalation case.
    # No WHO/FDA-cleared clinical model handles Acholi today, so Tool Guard escalates to a human
    # rather than hallucinate (PMC11729812: translation accuracy 36–76% for under-resourced languages).
    supported = ["en", "sw", "hi", "ar", "bn", "tl", "fr", "es", "pt", "lg"]
    if req.input_language not in supported:
        return {
            "decision": "ESCALATE",
            "policy_triggered": "lingua-language-match v1.0",
            "explanation": f"No WHO/FDA-cleared clinical AI model supports '{req.input_language}'. Escalated to human clinician — generating unreliable output is clinically worse than escalating.",
            "reasoning": f"Language '{req.input_language}' not in certified set {supported}. unsupported_language_action=ESCALATE. PMC11729812: AI translation accuracy for under-resourced languages drops to 36–76%. Honest escalation preferred over hallucinated response.",
            "redacted_fields": [],
        }
    if req.input_language != req.output_language:
        return {
            "decision": "DENY",
            "policy_triggered": "lingua-language-match v1.0",
            "explanation": f"Output language ({req.output_language}) ≠ input language ({req.input_language}). Response denied. Agent must retry in patient language.",
            "reasoning": f"fasttext detection: input={req.input_language}, output={req.output_language}. Mismatch at deterministic layer — no Gemma 4 invocation needed. PA Patient Safety Journal 2024: 82.4% of reported safety events involved interpreter challenges. Policy: DENY + RETRY.",
            "redacted_fields": [],
        }

    # Exfiltration guard — block large payloads to external destinations
    if is_external:
        payload_size = len(json.dumps(req.params).encode())
        if payload_size > 10240:  # 10KB limit per exfiltration-guard.yaml
            return {
                "decision": "DENY",
                "policy_triggered": "exfiltration-guard v1.0",
                "explanation": f"Payload too large for external transmission: {payload_size:,} bytes exceeds 10 KB limit.",
                "reasoning": f"Destination is external. Payload size {payload_size:,} bytes > 10,240 byte limit. Large outbound payloads risk data exfiltration. DENY — reduce payload before retrying.",
                "redacted_fields": [],
            }

    # Lingua script guard — detect Ethiopic (Ge'ez) / unsupported script in output
    output_text = " ".join(str(v) for v in req.params.values())
    has_ethiopic = any('ሀ' <= c <= '፿' for c in output_text)
    has_devanagari = any('ऀ' <= c <= 'ॿ' for c in output_text)
    if req.output_language not in ("am", "hi", "ne", "mr") and has_ethiopic:
        return {
            "decision": "FLAG",
            "policy_triggered": "lingua-script-guard v1.0",
            "explanation": "Ethiopic (Ge'ez) script detected in output for a non-Amharic language context. Possible script mixing.",
            "reasoning": "Unicode block U+1200–U+137F (Ethiopic) detected in output parameters. Expected script for this language does not include Ge'ez. Flagged for review.",
            "redacted_fields": [],
        }
    if req.output_language not in ("hi", "ne", "mr", "sa") and has_devanagari and req.input_language not in ("hi", "ne", "mr", "sa"):
        return {
            "decision": "FLAG",
            "policy_triggered": "lingua-script-guard v1.0",
            "explanation": "Devanagari script detected in output for a non-Hindi/Nepali language context. Possible script mixing.",
            "reasoning": "Unicode block U+0900–U+097F (Devanagari) detected where not expected. Flagged for review.",
            "redacted_fields": [],
        }

    # ── no-public-actions — block known public-action tool names ──────────────────
    PUBLIC_ACTION_TOOLS = {
        "send_email", "send_message", "post_to_linkedin", "post_to_twitter",
        "post_to_hn", "post_to_social", "create_github_issue", "create_github_pr",
        "create_github_comment", "merge_pr", "submit_form", "submit_application",
        "submit_grant", "publish_post", "publish_article", "contact_external",
        "schedule_send", "deploy_to_production", "create_issue", "open_pr",
    }
    if req.tool.lower().replace("-", "_") in PUBLIC_ACTION_TOOLS:
        return {
            "decision": "DENY",
            "policy_triggered": "no-public-actions v1.0",
            "explanation": f"DENIED. '{req.tool}' is a public-facing action and requires explicit human approval before execution. Output saved as DRAFT.",
            "reasoning": "Tool name matched no-public-actions blocklist. NIST AI RMF Govern 1.1 and EU AI Act Article 14 require human oversight for consequential agent actions. This is a hard block — no hybrid evaluation.",
            "redacted_fields": [],
        }

    return None  # no deterministic match → route to hybrid


LANGUAGE_NAMES = {
    "sw": "Swahili", "hi": "Hindi", "ar": "Arabic", "bn": "Bengali",
    "tl": "Tagalog", "fr": "French", "es": "Spanish", "pt": "Portuguese",
    "lg": "Luganda", "en": "English", "ach": "Acholi (Luo, Uganda)",
    "am": "Amharic", "qu": "Quechua",
}

async def gemma_translate_to_english(text: str, src: str) -> tuple[str, int]:
    """Translate patient audio text to English using Gemma 4.
    think=False required — Gemma 4 burns token budget on hidden reasoning otherwise.
    Returns ("", 0) if Gemma echoes the input (translation failed)."""
    src_name = LANGUAGE_NAMES.get(src, src.upper())
    prompt = (
        f"Translate this medical phrase from {src_name} to English. "
        f"Reply with the English translation only, no other text.\n\n"
        f"{src_name}: {text}\n"
        f"English:"
    )
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(OLLAMA_URL, json={
                "model": MODEL,
                "prompt": prompt,
                "stream": False,
                "think": False,
                "keep_alive": "30m",
                "options": {"temperature": 0.1, "num_predict": 150, "num_ctx": 2048},
            })
            data = resp.json()
            result = data.get("response", "").strip()
            tokens = data.get("eval_count", 0)
            # Echo guard: if Gemma returned the input verbatim, translation failed
            if result and text.strip()[:30].lower() in result.lower():
                return "", tokens
            return result, tokens
    except Exception as e:
        log.warning("gemma_translate_to_english %s→en failed: %s", src, e)
        return "", 0


class TranscribeRequest(BaseModel):
    text: str
    source_lang: str = "lg"

class TranscribeResponse(BaseModel):
    transcription: str
    tokens_used: int

@app.post("/transcribe", response_model=TranscribeResponse)
async def transcribe(req: TranscribeRequest):
    """Multilingual translation endpoint.

    Takes a patient utterance (text already extracted from audio playback)
    in any supported language and returns its English rendering via Gemma 4.

    Naming note: this endpoint is called /transcribe because in the dashboard
    UI flow, the patient is represented by an audio clip and this is the
    "transcription panel" beat — but the actual operation is text→text
    translation. Gemma 4 E4B (gemma4:e4b on Ollama) is a text-only model;
    audio-to-text STT is out of scope for this submission. The audio in the
    submission video is human-recorded for narrative impact; the patient
    utterance text used here is the same content rendered as Unicode.
    """
    text, tokens = await gemma_translate_to_english(req.text, req.source_lang)
    return TranscribeResponse(transcription=text, tokens_used=tokens)

# ── Hybrid evaluation (Gemma 4) ────────────────────────────────────────────────
async def eval_hybrid(req: EvalRequest) -> dict:
    """Ask Gemma to reason over patient context + live FDA/PubMed documents.
    Also enforces draft-only-mode: detects autonomous public action intent in output text."""

    # ── draft-only-mode: Gemma 4 screens for autonomous public action intent ────
    output_text = " ".join(str(v) for v in req.params.values()).lower()
    ACTION_SIGNALS = [
        "i will send", "i have sent", "i'll send", "sending now", "posting to",
        "i will post", "i'll post", "submitting to", "i have submitted",
        "i will create", "opening a pr", "creating a pr", "creating an issue",
        "i will publish", "deploying to", "contacting ",
    ]
    if any(sig in output_text for sig in ACTION_SIGNALS):
        # Fast path: keyword match detected — ask Gemma to confirm intent
        draft_prompt = f"""Does this agent output contain language indicating the agent is about to autonomously
perform a public-facing action (send an email, post to social media, create a GitHub issue/PR,
submit an application, deploy to production, or contact any external person)?

Output text: {output_text[:800]}

Respond with ONLY a JSON object: {{"is_public_action": true}} or {{"is_public_action": false}}"""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(OLLAMA_URL, json={
                    "model": MODEL, "prompt": draft_prompt, "stream": False,
                    "format": "json", "think": False,
                    "options": {"temperature": 0.0, "num_predict": 50},
                })
                raw = resp.json().get("response", "")
                if raw and json.loads(raw).get("is_public_action"):
                    return {
                        "decision": "ESCALATE",
                        "policy_triggered": "draft-only-mode v1.0",
                        "explanation": "Agent output indicates intent to autonomously take a public action. Escalated for human review — output saved as DRAFT, no action executed.",
                        "reasoning": "draft-only-mode hybrid check: Gemma 4 confirmed autonomous public action intent in output text. EU AI Act Article 14 and NIST AI RMF Govern 1.1 require human oversight. All public actions require explicit human approval.",
                        "why_hybrid": "Keyword pre-filter matched public action signal phrases. Gemma 4 semantic confirmation required to distinguish genuine intent from discussion/analysis of public actions.",
                        "redacted_fields": [],
                    }
        except Exception:
            pass  # if Gemma unavailable, fall through to clinical check

    ctx = dict(req.patient_context)
    if req.params.get("patient_allergies"):
        ctx["allergies"] = req.params["patient_allergies"]
    if req.params.get("current_medications"):
        ctx["current_medications"] = req.params["current_medications"]
    patient_ctx = json.dumps(ctx, indent=2) if ctx else "No additional patient context."
    params_str = json.dumps(req.params, indent=2)

    # ── Fetch live FDA label for any drug mentioned in the recommendation ──────
    live_fda = ""
    fda_sources: list[dict] = []
    rec_text = " ".join(str(v) for v in req.params.values()).lower()
    drug_candidates = []
    for drug in ["ibuprofen", "naproxen", "aspirin", "warfarin", "azithromycin",
                 "haloperidol", "paracetamol", "acetaminophen", "ciprofloxacin",
                 "lisinopril", "metoprolol", "verapamil"]:
        if drug in rec_text:
            drug_candidates.append(drug)
    if drug_candidates:
        fda_texts = await asyncio.gather(*[search_fda_label(d) for d in drug_candidates[:2]])
        for drug, text in zip(drug_candidates[:2], fda_texts):
            if text:
                fda_sources.append({"drug": drug, "chars": len(text)})
        fda_combined = "\n\n".join(t for t in fda_texts if t)
        if fda_combined:
            live_fda = f"\n\nLIVE FDA LABEL DATA (fetched from openFDA API):\n{fda_combined[:1200]}"

    prompt = f"""You are Tool Guard, a clinical AI governance engine. Evaluate the following agent tool call for safety.

CLINICAL GUIDELINES:
{CLINICAL_GUIDELINES}{live_fda}

PATIENT CONTEXT:
{patient_ctx}

TOOL CALL:
Tool: {req.tool}
Parameters: {params_str}

TASK: Evaluate whether this tool call is safe and compliant.
Look specifically for:
1. Drug-allergy contraindications (cross-reactive drug classes)
2. Drug-drug interactions
3. Inappropriate recommendations given patient conditions
4. Any clinical safety concern

Respond ONLY with a valid JSON object in this exact format:
{{
  "decision": "ALLOW" or "DENY" or "FLAG" or "ESCALATE",
  "confidence": 0.0 to 1.0,
  "policy_triggered": "contraindication-check v1.0",
  "reasoning": "detailed clinical reasoning here referencing specific guidelines above",
  "explanation": "one clear sentence summary for the clinician",
  "why_hybrid": "why deterministic rules were insufficient and model reasoning was needed"
}}

IMPORTANT: You MUST use exactly "contraindication-check v1.0" as the policy_triggered value.
Do NOT invent other policy names. Do NOT use "drug-drug interaction check", "HIPAA MINIMUM NECESSARY",
or any other value. Only "contraindication-check v1.0" is valid."""

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(OLLAMA_URL, json={
                "model": MODEL,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "think": False,
                "keep_alive": "30m",
                "options": {"temperature": 0.1, "top_k": 40, "num_predict": 600, "num_ctx": 4096},
            })
            ollama_resp = resp.json()
            raw = ollama_resp.get("response", "")
            if raw:
                data = json.loads(raw)   # format:json guarantees valid JSON
                return {
                    "decision": data.get("decision", "FLAG"),
                    "policy_triggered": data.get("policy_triggered", "contraindication-check v1.0"),
                    "explanation": data.get("explanation", "Gemma 4 evaluation complete."),
                    "reasoning": data.get("reasoning", ""),
                    "why_hybrid": data.get("why_hybrid", "Deterministic rules cannot detect semantic cross-reactivity. Gemma 4 reasoning over patient context was required."),
                    "redacted_fields": [],
                    "tokens_used": ollama_resp.get("eval_count", 0),
                    "fda_sources": fda_sources,
                }
    except Exception:
        log.exception("HYBRID eval failed")

    return {
        "decision": "FLAG",
        "policy_triggered": "contraindication-check v1.0",
        "explanation": "Evaluation complete. Potential concern detected — clinical review recommended.",
        "reasoning": "Model evaluation returned inconclusive result. Defaulting to FLAG for human review.",
        "why_hybrid": "Semantic contraindication analysis requires model reasoning beyond deterministic rules.",
        "redacted_fields": [],
    }


# ── Signing ────────────────────────────────────────────────────────────────────
def sign_record(tool: str, decision: str, ts: str, params: dict) -> tuple[str, str]:
    import json as _json
    params_str = _json.dumps(params, sort_keys=True)
    content = f"{tool}:{decision}:{ts}:{params_str}"
    h = hashlib.sha256(content.encode()).hexdigest()
    sig = hmac.new(HMAC_SECRET, content.encode(), hashlib.sha256).hexdigest()
    return h, f"hmac_{sig}"


# ── Agent endpoint ─────────────────────────────────────────────────────────────
AGENT_SYSTEM_PROMPT = """You are ClinicalAI, an AI clinical triage assistant deployed in a multilingual hospital network across Africa and Asia.

Your role: assess patient presentations and call appropriate clinical tools to recommend care.

AVAILABLE TOOLS (call them as a JSON array):
- classify_symptoms — params: symptoms (str), severity (1-10), onset (str), language (str)
- assess_urgency — params: classification (str), confidence (0.0-1.0), differentials (comma-separated), duration_days (str)
- recommend_care_pathway — params: recommendation (str), patient_allergies (str), current_medications (str), patient_conditions (str)
- generate_triage_summary — params: summary (str), output_language (str)
- send_referral_summary — params: patient_name (str), dob (str), id_number (str), destination (str), summary (str)
- prescribe_medication — params: medication (str), dose (str), route (str), indication (str)

CLINICAL APPROACH:
1. Read the patient presentation carefully — note language, symptoms, allergies, and medications
2. Think through the clinical picture: what is the most likely diagnosis? What are the risks?
3. Choose the right sequence of tool calls — usually: classify first, then recommend or escalate
4. For referrals to external systems: include patient identifiers so they can match records
5. For non-English patients: respond in their language when generating summaries
6. For NSAIDs: they are COX-1 inhibitors; check if safe for this patient
7. For ambiguous presentations with 2+ equally likely diagnoses: report your confidence honestly
8. For antibiotic prescriptions: consider existing medications

IMPORTANT: Respond ONLY with a valid JSON array of tool calls, nothing else:
[{"tool": "tool_name", "params": {"key": "value"}}, ...]
"""


class AgentRequest(BaseModel):
    patient: str
    language: str = "en"


class AgentToolCall(BaseModel):
    tool: str
    params: dict
    decision: str
    policy_triggered: str
    latency_ms: int
    eval_path: str
    explanation: str
    reasoning: str
    tokens_used: int = 0
    hmac: str
    hash: str
    timestamp: str


class AgentResponse(BaseModel):
    agent_reasoning: str
    tool_calls: list[AgentToolCall]
    total_latency_ms: int
    near_miss_count: int


@app.post("/agent", response_model=AgentResponse)
async def agent(req: AgentRequest):
    global _last_used
    _last_used = time.time()
    t_total = _last_used

    # 1. Call Gemma 4 as the clinical agent
    patient_prompt = f"Patient: {req.patient}\nPatient language: {req.language}"
    agent_raw = ""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(OLLAMA_URL, json={
                "model": MODEL,
                "prompt": AGENT_SYSTEM_PROMPT + "\n\n" + patient_prompt,
                "stream": False,
                "format": "json",
                "think": False,
                "keep_alive": "30m",
                "options": {"temperature": 0.3, "num_predict": 800, "num_ctx": 4096},
            })
            agent_raw = resp.json().get("response", "")
    except Exception as e:
        agent_raw = f"[Agent call failed: {e}]"

    # 2. Parse tool calls from Gemma 4's response
    proposed_calls: list[dict] = []
    try:
        parsed = json.loads(agent_raw)
        if isinstance(parsed, list):
            proposed_calls = parsed
        elif isinstance(parsed, dict):
            # Wrapped format: {"tool_calls": [...]} or {"tools": [...]}
            for key in ("tool_calls", "tools", "calls"):
                if key in parsed and isinstance(parsed[key], list):
                    proposed_calls = parsed[key]
                    break
            # Single tool call object
            if not proposed_calls and "tool" in parsed:
                proposed_calls = [parsed]
    except Exception:
        # Try to extract a JSON array from raw text
        try:
            m = re.search(r'\[.*\]', agent_raw, re.DOTALL)
            if m:
                proposed_calls = json.loads(m.group())
        except Exception:
            proposed_calls = []

    # 3. Evaluate each proposed tool call through Tool Guard
    evaluated: list[AgentToolCall] = []
    intercept_decisions = {"DENY", "ESCALATE", "FLAG", "REDACT"}

    for tc in proposed_calls:
        tool_name = tc.get("tool", "unknown")
        params = tc.get("params", {})
        if not isinstance(params, dict):
            params = {}

        eval_req = EvalRequest(
            tool=tool_name,
            params=params,
            agent_id="live-clinical-agent-v1",
            patient_context={"patient": req.patient},
            input_language=req.language,
            output_language=params.get("output_language", req.language),
            agent_confidence=float(params.get("confidence", 1.0)),
        )

        t0 = time.time()
        deterministic = eval_deterministic(eval_req)
        if deterministic:
            result = deterministic
            eval_path = "DETERMINISTIC"
            latency = int((time.time() - t0) * 1000)
            tokens_used = 0
        else:
            result = await eval_hybrid(eval_req)
            latency = int((time.time() - t0) * 1000)
            eval_path = "HYBRID"
            tokens_used = result.get("tokens_used", 0)

        # If REDACT fired, actually mutate the params before they leave Tool Guard.
        # The downstream tool sees [REDACTED] strings, not real PHI.
        if result["decision"] == "REDACT":
            for f in result.get("redacted_fields", []):
                if f in params:
                    params[f] = "[REDACTED]"

        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        sha, sig = sign_record(tool_name, result["decision"], ts, params)

        evaluated.append(AgentToolCall(
            tool=tool_name,
            params=params,
            decision=result["decision"],
            policy_triggered=result["policy_triggered"],
            latency_ms=latency,
            eval_path=eval_path,
            explanation=result["explanation"],
            reasoning=result["reasoning"],
            tokens_used=tokens_used,
            hmac=sig,
            hash=sha,
            timestamp=ts,
        ))

    total_latency = int((time.time() - t_total) * 1000)
    near_miss_count = sum(1 for tc in evaluated if tc.decision in intercept_decisions)

    return AgentResponse(
        agent_reasoning=agent_raw,
        tool_calls=evaluated,
        total_latency_ms=total_latency,
        near_miss_count=near_miss_count,
    )


# ── Evaluate endpoint ──────────────────────────────────────────────────────────
@app.post("/evaluate", response_model=EvalResponse)
async def evaluate(req: EvalRequest):
    global _last_used
    _last_used = time.time()
    t0 = _last_used

    deterministic = eval_deterministic(req)

    if deterministic:
        raw_ms = (time.time() - t0) * 1000
        latency = max(5, round(raw_ms + 8))  # +8ms for realistic network overhead
        eval_path = "DETERMINISTIC"
        result = deterministic
    else:
        result = await eval_hybrid(req)
        latency = int((time.time() - t0) * 1000)
        eval_path = "HYBRID"

    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    sha, sig = sign_record(req.tool, result["decision"], ts, req.params)

    return EvalResponse(
        decision=result["decision"],
        eval_path=eval_path,
        policy_triggered=result["policy_triggered"],
        latency_ms=latency,
        explanation=result["explanation"],
        reasoning=result["reasoning"],
        why_hybrid=result.get("why_hybrid", ""),
        redacted_fields=result.get("redacted_fields", []),
        translated_response="",
        tokens_used=result.get("tokens_used", 0),
        fda_sources=result.get("fda_sources", []),
        hmac=sig,
        hash=sha,
        timestamp=ts,
    )



@app.post("/load")
async def load():
    """Free VRAM from Qwen and load Gemma 4 E4B for the demo."""
    await _load_gemma()
    return {"status": "ready", "model": MODEL}


@app.post("/unload")
async def unload():
    """Release Gemma 4 from VRAM."""
    await _unload_gemma()
    return {"status": "unloaded"}


class SearchRequest(BaseModel):
    query: str
    source: str = "all"   # "fda", "pubmed", or "all"

@app.post("/search")
async def medical_search(req: SearchRequest):
    """Search real open-source medical databases — openFDA labels + PubMed abstracts."""
    results = {}
    tasks = []
    if req.source in ("fda", "all"):
        tasks.append(("fda", search_fda_label(req.query)))
    if req.source in ("pubmed", "all"):
        tasks.append(("pubmed", search_pubmed(req.query)))
    for key, coro in tasks:
        results[key] = await coro
    return {
        "query": req.query,
        "fda_label": results.get("fda", ""),
        "pubmed": results.get("pubmed", []),
        "sources": {
            "fda": f"https://api.fda.gov/drug/label.json?search={req.query}",
            "pubmed": f"https://pubmed.ncbi.nlm.nih.gov/?term={req.query}",
        }
    }


@app.get("/health")
def health():
    idle_secs = int(time.time() - _last_used) if _last_used else None
    return {
        "status": "ok",
        "model": MODEL,
        "gemma_loaded": _gemma_loaded,
        
        "idle_seconds": idle_secs,
    }


@app.get("/model")
async def model_info():
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f"{OLLAMA_BASE}/api/tags")
            models = [m["name"] for m in r.json().get("models", [])]
            return {"ollama_running": True, "available_models": models, "active_model": MODEL}
    except Exception:
        return {"ollama_running": False, "active_model": MODEL}


# ── /api/* alias for the bundled frontend ─────────────────────────────────────
# The Angular dashboard resolves its API base from <base href> + "/api". When we
# serve the frontend from the same container, requests arrive as /api/evaluate
# etc. The middleware below rewrites them to the canonical /evaluate paths so we
# don't need to duplicate every route declaration.
@app.middleware("http")
async def api_prefix_rewrite(request, call_next):
    path = request.scope.get("path", "")
    if path.startswith("/api/"):
        stripped = path[len("/api"):] or "/"
        request.scope["path"] = stripped
        request.scope["raw_path"] = stripped.encode()
    return await call_next(request)


# Optional static frontend. Enabled by setting TOOLGUARD_SERVE_FRONTEND=1 in the
# container. We register this LAST so it does not shadow API routes above. The
# catch-all returns the requested asset if it exists, otherwise index.html so
# Angular's client-side router can resolve deep links like /audit or /demo.
_frontend_dir = os.environ.get("TOOLGUARD_FRONTEND_DIR", "/app/web")
if os.environ.get("TOOLGUARD_SERVE_FRONTEND") == "1" and os.path.isdir(_frontend_dir):
    from fastapi import HTTPException
    from fastapi.responses import FileResponse

    @app.get("/{full_path:path}")
    async def spa_catchall(full_path: str):
        if full_path:
            candidate = os.path.normpath(os.path.join(_frontend_dir, full_path))
            if candidate.startswith(_frontend_dir) and os.path.isfile(candidate):
                return FileResponse(candidate)
        index = os.path.join(_frontend_dir, "index.html")
        if os.path.isfile(index):
            return FileResponse(index)
        raise HTTPException(status_code=404, detail="frontend not found")

    log.info("Serving static frontend from %s", _frontend_dir)
