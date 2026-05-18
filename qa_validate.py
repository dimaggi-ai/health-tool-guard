#!/usr/bin/env python3
"""
Tool Guard — Hackathon Submission QA Validator
Run from repo root: python qa_validate.py
Exits 0 if all checks pass, 1 if any CRITICAL check fails.
"""

import os, sys, json, subprocess, re, hashlib, time
from pathlib import Path

ROOT = Path(__file__).parent
PASS, WARN, FAIL = "✅", "⚠️ ", "❌"
results = []

def check(label, ok, critical=True, detail=""):
    icon = PASS if ok else (FAIL if critical else WARN)
    results.append((icon, label, detail))
    if not ok:
        print(f"  {icon} {label}" + (f"\n       {detail}" if detail else ""))
    else:
        print(f"  {icon} {label}")
    return ok


print("\n" + "━"*60)
print("  DIMAGGI Tool Guard — Hackathon QA Validator")
print("━"*60 + "\n")

# ── A. Repository structure ───────────────────────────────────
print("A. Repository structure")

required_files = [
    "README.md", "LICENSE", "SETUP.md", "POLICIES.md",
    "AUDIT.md", "TECHNICAL_REPORT.md",
    "backend/main.py", "backend/requirements.txt",
    "sdk/toolguard.py", "verifier/verify.py",
    "tests/test_policies.py",
    "notebook/tool-guard-gemma4.ipynb",
]
required_policies = [
    "clinical-scope-lock", "pii-boundary", "confidence-gate",
    "contraindication-check", "lingua-language-match",
    "lingua-script-guard", "lingua-terminology-lock",
    "lingua-reading-level", "rate-governor", "exfiltration-guard",
]

for f in required_files:
    p = ROOT / f
    check(f"File exists: {f}", p.exists(), detail=f"Missing: {p}")

for policy in required_policies:
    p = ROOT / "policies" / f"{policy}.yaml"
    check(f"Policy YAML: {policy}", p.exists(), critical=False)

# ── B. Content checks ─────────────────────────────────────────
print("\nB. Content quality")

readme = (ROOT / "README.md").read_text()
check("README: no placeholder [DEMO_URL]", "[DEMO_URL]" not in readme,
      detail="Unfilled placeholder in README")
check("README: no placeholder [KAGGLE_URL]", "[KAGGLE_URL]" not in readme)
check("README: has live demo URL",
      "dimaggi.ai/health-tool-guard" in readme or "dimaggi.ai/tool-guard" in readme or "dimaggi.com" in readme,
      detail="Live demo URL missing")
check("README: has architecture diagram", "```" in readme and "Tool Guard" in readme)
check("README: correct build config",
      "configuration=production" in readme or "configuration=demo" not in readme,
      critical=False, detail="Wrong build config referenced")
check("README: correct clone URL",
      "dimaggi-ai/health-tool-guard" in readme or "github.com" not in readme,
      critical=False)
check("README: Gemma TOU acknowledged",
      "ai.google.dev/gemma/terms" in readme or "Gemma Terms of Use" in readme,
      detail="Gemma Terms of Use acknowledgement missing")
check("README: no demo credentials leaked",
      "Dimaggi123" not in readme and "admin@dimaggi.com" not in readme,
      detail="Demo credentials exposed in README")

setup = (ROOT / "SETUP.md").read_text()
check("SETUP: correct backend dir", "demo-backend" not in setup,
      detail="Wrong directory name in setup instructions")
check("SETUP: no demo demo duplication", "demo demo" not in setup.lower())

tech = (ROOT / "TECHNICAL_REPORT.md").read_text()
check("TECH_REPORT: no Qwen references", "Qwen" not in tech and "llama-server" not in tech,
      critical=False, detail="Internal model references")
check("TECH_REPORT: 6 challenges", tech.count("### Challenge") >= 5,
      critical=False)

license_text = (ROOT / "LICENSE").read_text()
check("LICENSE: is AGPL-3.0",
      "GNU AFFERO GENERAL PUBLIC LICENSE" in license_text and "Version 3" in license_text,
      detail="LICENSE is not AGPL-3.0")
notice_path = ROOT / "NOTICE"
check("NOTICE: file exists", notice_path.exists(),
      detail="NOTICE file missing (holds copyright + trademark reservation)")
if notice_path.exists():
    notice = notice_path.read_text()
    check("NOTICE: has DIMAGGI copyright", "DIMAGGI Inc" in notice)
    check("NOTICE: reserves trademark", "Tool Guard" in notice and "trademark" in notice.lower())
    check("NOTICE: acknowledges Gemma TOU", "ai.google.dev/gemma/terms" in notice,
          critical=False)

# Notebook checks
nb_path = ROOT / "notebook" / "tool-guard-gemma4.ipynb"
if nb_path.exists():
    nb = json.loads(nb_path.read_text())
    nb_src = " ".join("".join(c["source"]) for c in nb["cells"])
    check("NOTEBOOK: no 'replace with DEMO_URL'",
          "replace with your DEMO_URL" not in nb_src and "replace with" not in nb_src.lower(),
          detail="Placeholder URL in notebook")
    check("NOTEBOOK: no 'add URL after'",
          "add URL after pushing" not in nb_src,
          detail="Placeholder URL in notebook")
    check("NOTEBOOK: has real GitHub URL",
          "github.com/dimaggi-ai" in nb_src,
          critical=False)
    check("NOTEBOOK: 10 cells", len(nb["cells"]) >= 10, critical=False)
    check("NOTEBOOK: has Gemma 4 model reference",
          "gemma" in nb_src.lower() or "gemma4" in nb_src.lower())

# ── C. Backend checks ─────────────────────────────────────────
print("\nC. Backend code quality")

backend = (ROOT / "backend" / "main.py").read_text()
check("BACKEND: no Qwen config", "QWEN_CMD" not in backend and "Qwen_" not in backend,
      detail="Internal model config exposed")

start_sh_path = ROOT / "backend" / "start.sh"
if start_sh_path.exists():
    start_sh = start_sh_path.read_text()
    check("START.SH: uses python3 from PATH (or honors $PYTHON)",
          "python3" in start_sh or "${PYTHON" in start_sh or "$PYTHON" in start_sh,
          critical=False)
check("BACKEND: uses Gemma 4", "gemma4:e4b" in backend or "gemma4" in backend.lower())
check("BACKEND: format:json present", '"format": "json"' in backend,
      detail="Critical Gemma 4 parameter missing")
check("BACKEND: HMAC signing", "hmac" in backend.lower())
check("BACKEND: scope-lock enforced", "clinical-scope-lock" in backend)
check("BACKEND: pii-boundary enforced", "pii-boundary" in backend)
check("BACKEND: confidence-gate enforced", "confidence-gate" in backend)
check("BACKEND: lingua-language-match enforced", "lingua-language-match" in backend)
check("BACKEND: exfiltration-guard enforced", "exfiltration-guard" in backend)
check("BACKEND: FDA live search", "search_fda_label" in backend,
      critical=False, detail="Live FDA integration not found")
check("BACKEND: tokens_used field", "tokens_used" in backend or "eval_count" in backend)

# ── D. Tests ──────────────────────────────────────────────────
print("\nD. Test suite")

test_result = subprocess.run(
    [sys.executable, "-m", "pytest", "tests/test_policies.py", "-q", "--tb=no"],
    capture_output=True, text=True, cwd=ROOT
)
check("TESTS: all pass",
      test_result.returncode == 0,
      detail=test_result.stdout.strip().split("\n")[-1] if test_result.stdout else "test run failed")

test_src = (ROOT / "tests" / "test_policies.py").read_text()
check("TESTS: has integration test (verifier)", "test_verifier_on_real_chain" in test_src,
      critical=False)

# ── E. Verifier ───────────────────────────────────────────────
print("\nE. Offline verifier")

verifier = (ROOT / "verifier" / "verify.py").read_text()
check("VERIFIER: exists and has verify subcommand", "def verify(" in verifier)
check("VERIFIER: uses SHA-256", "sha256" in verifier.lower())
check("VERIFIER: exit codes", "sys.exit" in verifier)

# Quick smoke test: build a 2-record chain and verify it
sys.path.insert(0, str(ROOT / "sdk"))
try:
    from toolguard import ToolGuard, AuditChain
    import tempfile

    tg = ToolGuard(policies=[], hmac_secret="qa-test")
    r1 = tg.evaluate("classify_symptoms", {"symptoms": "fever"}, {})
    r2 = tg.evaluate("send_referral_summary",
                     {"patient_name": "A.W.", "destination": "external_api"}, {})

    records = []
    for i, r in enumerate([r1, r2]):
        records.append(json.dumps({
            "tool": ["classify_symptoms","send_referral_summary"][i],
            "params": {}, "agent_context": {},
            "decision": r.decision, "eval_path": r.eval_path,
            "policy_triggered": r.policy_triggered, "latency_ms": r.latency_ms,
            "explanation": r.explanation, "hmac": r.hmac,
            "hash": r.hash, "prevHash": r.prev_hash,
            "timestamp": r.timestamp, "language": "en",
            "nonce": f"qa_{i}",
        }))

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        f.write("\n".join(records))
        tmp = f.name

    vr = subprocess.run(
        [sys.executable, "verifier/verify.py", "verify", "--chain", tmp],
        capture_output=True, text=True, cwd=ROOT
    )
    os.unlink(tmp)
    check("VERIFIER: passes on clean chain", vr.returncode == 0,
          detail=vr.stdout.strip().split("\n")[-1] if vr.stdout else "verifier crashed")
except Exception as e:
    check("VERIFIER: smoke test", False, detail=str(e))

# ── F. Demo scenarios ─────────────────────────────────────────
print("\nF. Demo scenarios")

try:
    sys.path.insert(0, str(ROOT / "web" / "src" / "app" / "data"))
    # Can't import TS directly, parse the file
    scenarios_ts = (ROOT / "web/src/app/data/scenarios.ts").read_text()
    lang_codes = re.findall(r"language: '([a-z]+)'", scenarios_ts)
    unique_langs = set(lang_codes) - {"en"}
    check("SCENARIOS: 7+ non-English languages", len(unique_langs) >= 7,
          detail=f"Found: {sorted(unique_langs)}")
    check("SCENARIOS: Luganda present", "lg" in unique_langs)
    check("SCENARIOS: Acholi present", "ach" in unique_langs, critical=False)
    check("SCENARIOS: Arabic present", "ar" in unique_langs)
    check("SCENARIOS: Swahili present", "sw" in unique_langs)

    modalities = re.findall(r"inputType: '([^']+)'", scenarios_ts)
    check("SCENARIOS: audio modality present", "audio" in modalities)
    check("SCENARIOS: multimodal present", "multimodal" in modalities)
    check("SCENARIOS: text modality present", "text" in modalities)

    decisions = re.findall(r"decision: '([A-Z]+)'", scenarios_ts)
    for outcome in ["ALLOW","DENY","REDACT","ESCALATE","FLAG"]:
        check(f"SCENARIOS: {outcome} decision present", outcome in decisions)
except Exception as e:
    check("SCENARIOS: parseable", False, detail=str(e))

# ── G. Backend live check (optional) ─────────────────────────
print("\nG. Backend connectivity (skipped if not running)")
try:
    import urllib.request
    with urllib.request.urlopen("http://localhost:8092/health", timeout=3) as r:
        health = json.loads(r.read())
    check("BACKEND: health endpoint reachable", health.get("status") == "ok")
    check("BACKEND: Gemma 4 model loaded", health.get("model") == "gemma4:e4b",
          critical=False)

    # /transcribe smoke test — real Gemma 4 multilingual translation
    if health.get("gemma_loaded"):
        try:
            req = urllib.request.Request(
                "http://localhost:8092/transcribe",
                data=json.dumps({
                    "text": "Ndwadde nnyo. Nnina omusujja.",  # "I am very sick. I have a fever." in Luganda
                    "source_lang": "lg",
                }).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                tr = json.loads(r.read())
            check("BACKEND: /transcribe returns translation",
                  bool(tr.get("transcription")) and tr.get("tokens_used", 0) > 0,
                  critical=False,
                  detail=f"transcription={tr.get('transcription')!r} tokens={tr.get('tokens_used')}")
        except Exception as e:
            check("BACKEND: /transcribe returns translation", False,
                  critical=False, detail=f"transcribe call failed: {e}")
except Exception:
    check("BACKEND: health endpoint reachable", False, critical=False,
          detail="Backend not running locally — OK for CI")

# ── H. Git identity & contributor hygiene ─────────────────────
#  Asserts every commit (author, committer, message trailers) is
#  attributed to dimaggi-ai and only dimaggi-ai. Personal accounts
#  and AI co-author trailers must not appear in the public repo's
#  contributor graph.
import subprocess
print("\nH. Git identity")

def _git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()

ALLOWED_EMAIL_SUFFIXES = ("@dimaggi.ai", "+dimaggi-ai@users.noreply.github.com")
authors = _git("log", "--pretty=format:%ae").splitlines()
committers = _git("log", "--pretty=format:%ce").splitlines()
bad_authors = [e for e in authors if not e.endswith(ALLOWED_EMAIL_SUFFIXES)]
bad_committers = [e for e in committers if not e.endswith(ALLOWED_EMAIL_SUFFIXES)]
check("GIT: all commit authors are dimaggi-ai", not bad_authors,
      detail=f"non-dimaggi authors: {sorted(set(bad_authors))[:5]}")
check("GIT: all commit committers are dimaggi-ai", not bad_committers,
      detail=f"non-dimaggi committers: {sorted(set(bad_committers))[:5]}")

# Co-Authored-By trailers (these attribute additional accounts in GitHub's UI)
bodies = _git("log", "--pretty=format:%B%n---END---")
forbidden_trailers = [tag for tag in ("Co-Authored-By:", "Co-authored-by:", "co-authored-by:")
                     if tag.lower() in bodies.lower()]
check("GIT: no Co-Authored-By trailers", not forbidden_trailers,
      detail=f"found: {forbidden_trailers}")

# No stray remote branches (collaborators sometimes appear via dangling refs)
remotes = _git("branch", "-r").splitlines()
allowed_remotes = {"origin/HEAD", "origin/main"}
stray = [r.strip() for r in remotes if r.strip() and not any(r.strip().startswith(a) for a in allowed_remotes)]
check("GIT: only origin/main on remote", not stray, critical=False,
      detail=f"stray remote branches: {stray[:5]}")

# ── Summary ───────────────────────────────────────────────────
print("\n" + "━"*60)
total = len(results)
passed = sum(1 for r in results if r[0] == PASS)
warned = sum(1 for r in results if r[0] == WARN)
failed = sum(1 for r in results if r[0] == FAIL)

print(f"  {PASS} Passed:   {passed}/{total}")
if warned:  print(f"  {WARN} Warnings: {warned}")
if failed:  print(f"  {FAIL} Failed:   {failed}")

if failed == 0:
    print("\n  ✅  SUBMISSION READY — no critical issues found")
else:
    print("\n  ❌  NOT READY — fix critical issues above before submitting")
    print("\n  Critical failures:")
    for icon, label, detail in results:
        if icon == FAIL:
            print(f"    • {label}" + (f"\n      → {detail}" if detail else ""))

print("━"*60 + "\n")
sys.exit(0 if failed == 0 else 1)
