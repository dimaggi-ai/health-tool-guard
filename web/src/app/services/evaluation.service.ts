import { Injectable } from '@angular/core';

// Resolve API base relative to the app's base href so it works at any subpath
const _base = (document.querySelector('base')?.getAttribute('href') ?? '/').replace(/\/$/, '');
const BACKEND = `${_base}/api`;

export interface EvalResult {
  decision: string;
  eval_path: string;
  policy_triggered: string;
  latency_ms: number;
  explanation: string;
  reasoning: string;
  why_hybrid: string;
  redacted_fields: string[];
  translated_response: string;
  tokens_used: number;
  fda_sources?: { drug: string; chars: number }[];
  hmac: string;
  hash: string;
  timestamp: string;
}

export interface HealthResult {
  status: string;
  model: string;
  gemma_loaded: boolean;
  qwen_running: boolean;
  idle_seconds: number | null;
}

export interface AgentToolCall {
  tool: string;
  params: Record<string, string>;
  decision: string;
  policy_triggered: string;
  latency_ms: number;
  eval_path: string;
  explanation: string;
  reasoning: string;
  tokens_used: number;
  hmac: string;
  hash: string;
  timestamp: string;
}

export interface AgentResult {
  agent_reasoning: string;
  tool_calls: AgentToolCall[];
  total_latency_ms: number;
  near_miss_count: number;
}

@Injectable({ providedIn: 'root' })
export class EvaluationService {

  async evaluate(tool: string, params: Record<string, string>, patientContext: object = {}, opts: Record<string, unknown> = {}): Promise<EvalResult> {
    const resp = await fetch(`${BACKEND}/evaluate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: AbortSignal.timeout(110000),
      body: JSON.stringify({
        tool, params,
        patient_context: patientContext,
        agent_confidence: (opts['confidence'] as number) ?? 1.0,
        input_language: (opts['inputLang'] as string) ?? 'en',
        output_language: (opts['outputLang'] as string) ?? 'en',
      })
    });
    return resp.json() as Promise<EvalResult>;
  }

  async transcribe(text: string, sourceLang: string): Promise<{transcription: string, tokens_used: number}> {
    try {
      const r = await fetch(`${BACKEND}/transcribe`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        signal: AbortSignal.timeout(20000),
        body: JSON.stringify({ text, source_lang: sourceLang })
      });
      return r.json();
    } catch {
      // Never return the input as the "translation" — silently fail with empty.
      return { transcription: '', tokens_used: 0 };
    }
  }

  async checkBackend(): Promise<boolean> {
    try {
      const r = await fetch(`${BACKEND}/health`, { signal: AbortSignal.timeout(2000) });
      if (!r.ok) return false;
      // Don't trust HTTP 200 alone — SPA fallback (error_page 404 -> index.html)
      // returns HTML with status 200. Require a JSON body with {status: "ok"}.
      const ct = r.headers.get('content-type') || '';
      if (!ct.includes('application/json')) return false;
      const data = await r.json();
      return data?.status === 'ok';
    } catch { return false; }
  }

  async getHealth(): Promise<HealthResult | null> {
    try {
      const r = await fetch(`${BACKEND}/health`, { signal: AbortSignal.timeout(3000) });
      return r.ok ? r.json() : null;
    } catch { return null; }
  }

  async loadGemma(): Promise<void> {
    await fetch(`${BACKEND}/load`, { method: 'POST', signal: AbortSignal.timeout(90000) });
  }

  async unloadGemma(): Promise<void> {
    await fetch(`${BACKEND}/unload`, { method: 'POST', signal: AbortSignal.timeout(10000) });
  }

  async runAgent(patient: string, language: string): Promise<AgentResult> {
    const r = await fetch(`${BACKEND}/agent`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: AbortSignal.timeout(120000),
      body: JSON.stringify({ patient, language })
    });
    return r.json();
  }

  async sha256(input: string): Promise<string> {
    // Use the unified helper from scenarios.ts (Web Crypto + pure-JS fallback for HTTP)
    const { sha256Hex } = await import('../data/scenarios');
    const h = await sha256Hex(input);
    return h.replace(/^sha256_/, '');
  }
}
