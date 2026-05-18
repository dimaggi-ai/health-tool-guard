import { Injectable, signal } from '@angular/core';
import { EvalResult } from './evaluation.service';

export interface LiveAuditRecord {
  id: string;
  seq: number;
  timestamp: string;
  agent: string;
  tool: string;
  decision: string;
  evalPath: string;
  latencyMs: number;
  tokensUsed: number;
  policy: string;
  explanation: string;
  reasoning: string;
  modality: string;
  language: string;
  scenario: string;
  hmac: string;
  hash: string;       // real SHA-256 via Web Crypto
  prevHash: string;   // hash of previous record — chain linkage
}

const GENESIS = 'sha256_' + '0'.repeat(64);

@Injectable({ providedIn: 'root' })
export class AuditChainService {
  private _records = signal<LiveAuditRecord[]>([]);
  readonly records = this._records.asReadonly();

  async append(result: EvalResult, meta: {
    tool: string; modality: string; language: string; scenario: string;
  }): Promise<void> {
    const all  = this._records();
    const prev = all[all.length - 1];
    const seq  = (prev?.seq ?? 0) + 1;

    const partial: Omit<LiveAuditRecord, 'hash'> = {
      id:          `rec-${seq}-${Date.now()}`,
      seq,
      timestamp:   result.timestamp || new Date().toISOString(),
      agent:       'clinical-triage-agent-v1',
      tool:        meta.tool,
      decision:    result.decision,
      evalPath:    result.eval_path,
      latencyMs:   result.latency_ms,
      tokensUsed:  result.tokens_used ?? 0,
      policy:      result.policy_triggered,
      explanation: result.explanation,
      reasoning:   result.reasoning ?? '',
      modality:    meta.modality,
      language:    meta.language,
      scenario:    meta.scenario,
      hmac:        result.hmac,
      prevHash:    prev?.hash ?? GENESIS,
    };

    // Real SHA-256 over the full record content (Web Crypto + pure-JS fallback for HTTP)
    const { sha256Hex } = await import('../data/scenarios');
    const hash = await sha256Hex(JSON.stringify(partial));
    this._records.update(rs => [...rs, { ...partial, hash }]);
  }

  // Re-verify the full chain by re-computing every hash
  async verify(): Promise<{ intact: boolean; brokenAt?: number }> {
    const rs = this._records();
    const { sha256Hex } = await import('../data/scenarios');
    for (let i = 0; i < rs.length; i++) {
      const r = rs[i];
      const { hash: _h, ...rest } = r;
      const computed = await sha256Hex(JSON.stringify(rest));
      if (computed !== r.hash) return { intact: false, brokenAt: i + 1 };
      if (i > 0 && r.prevHash !== rs[i - 1].hash) return { intact: false, brokenAt: i + 1 };
    }
    return { intact: true };
  }

  get isEmpty() { return this._records().length === 0; }
  get count()   { return this._records().length; }
}
