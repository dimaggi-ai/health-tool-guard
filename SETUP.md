# DIMAGGI Tool Guard — Local Setup

The **recommended path** is `docker compose -f docker/compose.yml up` from the repository root — see the [Quick Start in the README](README.md#quick-start). The notes below cover the native (non-Docker) install for developers who want to iterate on the code directly.

## Requirements

| Requirement | Minimum |
|-------------|---------|
| Python | 3.10+ |
| Node.js | 20+ |
| GPU VRAM | 8 GB+ for Gemma 4 E4B on-device inference (falls back to CPU otherwise) |
| Ollama | latest |

---

## Native Install

```bash
# 1. Install Ollama — https://ollama.ai (follow the instructions for your OS)

# 2. Pull Gemma 4 E4B
ollama pull gemma4:e4b

# 3. Start the backend (port 8092, default)
cd backend
pip install -r requirements.txt
bash start.sh

# 4. Build and serve the dashboard
cd ../web
npm install
npm start                     # dev server on http://localhost:4200 with /api proxy

# Or, for a production-style build served as static files:
# npm run build -- --configuration=production
# Then serve web/dist/tool-guard/browser/ with any static file server.
```

> Without a GPU, Ollama falls back to CPU. Deterministic checks remain instant; HYBRID Gemma 4 checks slow to 5-15 s per request. The audit chain, policy tests, and scripted scenarios all run regardless.

---

## Verifying the Audit Chain

After running any scenario in the UI, download the audit log from the **Audit Chain** page and verify it locally:

```bash
python verifier/verify.py verify --chain audit.jsonl
# or, after `pip install -e sdk/`:
toolguard verify --chain audit.jsonl
```

A passing chain prints `✓ Chain intact — no tampering detected`. Edit any byte in `audit.jsonl` and re-run to see `✗ TAMPERED at record N`.

---

## Running Tests

```bash
pytest tests/test_policies.py -v        # 14 policy tests — audit-chain tamper detection included
cd web && npm test                       # Angular unit tests
```

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `OLLAMA_BASE` | `http://localhost:11434` | Ollama API endpoint. The Docker setup sets this to `http://ollama:11434`. |
| `TOOLGUARD_HMAC_SECRET` | `toolguard-demo-2026` | HMAC signing key for the audit chain. |
| `TOOLGUARD_CORS_ORIGINS` | *(empty)* | Comma-separated extra CORS origins (defaults already include `http://localhost:4200`, `https://dimaggi.ai`, `https://dimaggi.com`). |
| `TOOLGUARD_SERVE_FRONTEND` | *(unset)* | Set to `1` to make the backend mount `TOOLGUARD_FRONTEND_DIR` (default `/app/web`) as static files. The bundled Dockerfile turns this on automatically. |
