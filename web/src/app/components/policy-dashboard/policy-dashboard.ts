import { Component } from '@angular/core';
import { NgFor, NgClass, DecimalPipe, NgIf } from '@angular/common';
import { buildAuditRecords } from '../../data/scenarios';

@Component({
  selector: 'app-policy-dashboard',
  standalone: true,
  imports: [NgFor, NgClass, DecimalPipe, NgIf],
  templateUrl: './policy-dashboard.html',
  styleUrl: './policy-dashboard.css'
})
export class PolicyDashboardComponent {
  records: any[] = [];
  async ngOnInit() { this.records = await buildAuditRecords(); }

  get totalCalls() { return this.records.length; }
  get allowCount() { return this.records.filter(r => r.decision === 'ALLOW').length; }
  get denyCount() { return this.records.filter(r => r.decision === 'DENY').length; }
  get redactCount() { return this.records.filter(r => r.decision === 'REDACT').length; }
  get escalateCount() { return this.records.filter(r => r.decision === 'ESCALATE').length; }
  get flagCount() { return this.records.filter(r => r.decision === 'FLAG').length; }
  get hybridCount() { return this.records.filter(r => r.evalPath === 'HYBRID').length; }
  get avgLatency() { return Math.round(this.records.reduce((a, r) => a + r.latencyMs, 0) / this.records.length); }
  // Session near-miss: each non-ALLOW decision averted a potential harm event valued at $2,400
  readonly perEventValue = 2400;
  get sessionNearMiss() { return this.records.filter(r => r.decision !== 'ALLOW').length * this.perEventValue; }
  readonly nearMissProjection = 87500; // 30-day projection shown in Overview

  get decisionDonut(): string {
    const t = this.totalCalls;
    if (!t) return 'conic-gradient(#e2e8f0 0% 100%)';
    let at = 0;
    const seg = (n: number, color: string) => {
      const pct = (n / t) * 100;
      const s = `${color} ${at.toFixed(2)}% ${(at + pct).toFixed(2)}%`;
      at += pct;
      return s;
    };
    return `conic-gradient(${[
      seg(this.allowCount,    '#22c55e'),
      seg(this.denyCount,     '#ef4444'),
      seg(this.redactCount,   '#f97316'),
      seg(this.escalateCount, '#3b82f6'),
      seg(this.flagCount,     '#8b5cf6'),
    ].join(', ')})`;
  }

  languages = [
    { code: 'sw', name: 'Swahili',  pct: 24, color: '#7c8cff' },
    { code: 'hi', name: 'Hindi',    pct: 18, color: '#5b6dff' },
    { code: 'ar', name: 'Arabic',   pct: 16, color: '#818cf8' },
    { code: 'lg', name: 'Luganda',  pct: 14, color: '#6366f1' },
    { code: 'bn', name: 'Bengali',  pct: 12, color: '#a5b4fc' },
    { code: 'tl', name: 'Tagalog',  pct: 8,  color: '#c7d2fe' },
    { code: 'qu', name: 'Quechua',  pct: 5,  color: '#e0e7ff' },
    { code: 'am', name: 'Amharic',  pct: 3,  color: '#eef2ff' },
  ];

  private policyConfig = [
    { name: 'clinical-scope-lock',    category: 'Clinical', path: 'deterministic', lastFired: '2m ago'  },
    { name: 'pii-boundary',           category: 'Clinical', path: 'deterministic', lastFired: '3m ago'  },
    { name: 'confidence-gate',        category: 'Clinical', path: 'deterministic', lastFired: '5m ago'  },
    { name: 'contraindication-check', category: 'Clinical', path: 'hybrid',        lastFired: '7m ago'  },
    { name: 'rate-governor',          category: 'Security', path: 'deterministic', lastFired: 'never'   },
    { name: 'exfiltration-guard',     category: 'Security', path: 'deterministic', lastFired: 'never'   },
    { name: 'lingua-language-match',  category: 'Lingua',   path: 'deterministic', lastFired: '4m ago'  },
    { name: 'lingua-script-guard',    category: 'Lingua',   path: 'deterministic', lastFired: '8m ago'  },
    { name: 'lingua-terminology-lock',category: 'Lingua',   path: 'hybrid',        lastFired: '9m ago'  },
    { name: 'lingua-reading-level',   category: 'Lingua',   path: 'hybrid',        lastFired: 'never'   },
  ];

  // Match counts derived live from AUDIT_RECORDS so dashboard and audit chain always
  // agree
  get policies() {
    const counts: Record<string, number> = {};
    for (const r of this.records) { counts[r.policy] = (counts[r.policy] ?? 0) + 1; }
    return this.policyConfig.map(p => ({ ...p, matches: counts[p.name] ?? 0 }));
  }

  get deterministicCount() { return this.records.filter(r => r.evalPath === 'DETERMINISTIC').length; }
  get deterministicPct()   { return this.records.length ? Math.round(this.deterministicCount / this.records.length * 100) : 0; }
  get hybridPct()          { return 100 - this.deterministicPct; }
  get policyCoverage()     { return this.records.length ? Math.round((this.records.length - this.allowCount) / this.records.length * 100) : 0; }

  // p50 and p95 latency from audit records
  get p50latency() {
    const sorted = [...this.records].sort((a, b) => a.latencyMs - b.latencyMs);
    return sorted[Math.floor(sorted.length * 0.5)]?.latencyMs ?? 0;
  }
  get p95latency() {
    const sorted = [...this.records].sort((a, b) => a.latencyMs - b.latencyMs);
    return sorted[Math.floor(sorted.length * 0.95)]?.latencyMs ?? 0;
  }

  // Live decision feed — most recent first, capped at 15 for display
  get feedRecords() { return [...this.records].reverse().slice(0, 15); }

  // Agent status cards derived from audit records
  get agentStats() {
    const agents = ['clinical-triage-agent-v1'];
    return agents.map(name => {
      const agentRecs = this.records.filter(r => r.agent === name);
      const denied = agentRecs.filter(r => ['DENY','REDACT','ESCALATE','FLAG'].includes(r.decision)).length;
      return {
        name,
        total: agentRecs.length,
        denyPct: agentRecs.length ? Math.round(denied / agentRecs.length * 100) : 0,
        lastActivity: '2m ago',
      };
    });
  }
}
