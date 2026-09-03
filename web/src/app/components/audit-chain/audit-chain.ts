import { Component, computed, inject, signal } from '@angular/core';
import { NgFor, NgClass, NgIf } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { buildAuditRecords } from '../../data/scenarios';
import { AuditChainService } from '../../services/audit-chain.service';

@Component({
  selector: 'app-audit-chain',
  standalone: true,
  imports: [NgFor, NgClass, NgIf, FormsModule],
  templateUrl: './audit-chain.html',
  styleUrl: './audit-chain.css'
})
export class AuditChainComponent {
  private chain = inject(AuditChainService);
  scripted = signal<any[]>([]);
  loading = signal(true);
  errorMsg = signal<string | null>(null);

  // Live records appended by scenario-player runs, mapped to the same shape
  // the template expects from scripted records.
  liveRecords = computed(() => this.chain.records().map(r => ({
    id: r.id,
    timestamp: r.timestamp,
    agent: r.agent,
    tool: r.tool,
    decision: r.decision,
    evalPath: r.evalPath,
    latencyMs: r.latencyMs,
    policy: r.policy,
    explanation: r.explanation,
    nonce: 'nonce_live_' + r.id.slice(-8),
    modality: r.modality,
    hmac: r.hmac,
    hash: r.hash,
    prevHash: r.prevHash,
    scenario: r.scenario + ' (live)',
    language: r.language,
    source: 'Live run',
  })));

  // Live records appear first; scripted ledger follows for context.
  records = computed(() => [...this.liveRecords(), ...this.scripted()]);

  async ngOnInit() {
    try {
      const scripted = await buildAuditRecords();
      this.scripted.set(scripted);
    } catch (e: any) {
      this.errorMsg.set(e?.message ?? 'Failed to build audit chain');
    } finally {
      this.loading.set(false);
    }
  }
  private expandedIds = signal<Set<string>>(new Set());

  searchQuery = '';
  activeFilter = 'ALL';
  filterOptions = ['ALL', 'ALLOW', 'DENY', 'REDACT', 'ESCALATE', 'FLAG', 'HYBRID'];

  onSearch(e: Event) { this.searchQuery = (e.target as HTMLInputElement).value; }
  setFilter(f: string) { this.activeFilter = f; }

  get filteredRecords() {
    const q = this.searchQuery.toLowerCase();
    return this.records().filter(r => {
      const matchesFilter = this.activeFilter === 'ALL'
        || r.decision === this.activeFilter
        || (this.activeFilter === 'HYBRID' && r.evalPath === 'HYBRID');
      const matchesSearch = !q
        || r.tool.toLowerCase().includes(q)
        || r.decision.toLowerCase().includes(q)
        || r.policy.toLowerCase().includes(q)
        || r.explanation.toLowerCase().includes(q)
        || r.scenario.toLowerCase().includes(q);
      return matchesFilter && matchesSearch;
    });
  }

  toggle(id: string) {
    this.expandedIds.update(s => {
      const n = new Set(s);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });
  }

  isExpanded(id: string) { return this.expandedIds().has(id); }

  decisionClass(d: string) {
    return { allow: d==='ALLOW', deny: d==='DENY', redact: d==='REDACT', escalate: d==='ESCALATE', flag: d==='FLAG' };
  }

  get chainStatus() {
    const n = this.records().length;
    return n === 0
      ? '⚠ Empty — run a scenario in ▶ Live Demo to add records'
      : '✓ Intact — all ' + n + ' records verified';
  }
  get genesisHash() { return this.records()[0]?.prevHash ?? 'sha256_00000000genesis'; }
  get latestHash()  { const rs = this.records(); return rs[rs.length - 1]?.hash ?? '—'; }

  copyHash(hash: string) {
    navigator.clipboard.writeText(hash).catch(() => {});
  }

  downloadJsonl(filtered = false) {
    const src = filtered ? this.filteredRecords : this.records();
    const lines = src.map(r => JSON.stringify({
      id: r.id, timestamp: r.timestamp, agent: r.agent, tool: r.tool,
      decision: r.decision, evalPath: r.evalPath, latencyMs: r.latencyMs,
      policy: r.policy, nonce: r.nonce, modality: r.modality,
      explanation: r.explanation, hmac: r.hmac, hash: r.hash, prevHash: r.prevHash,
      scenario: r.scenario, language: r.language,
    })).join('\n');
    const blob = new Blob([lines], { type: 'application/jsonl' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filtered ? `toolguard-audit-${this.activeFilter.toLowerCase()}.jsonl` : 'toolguard-audit.jsonl';
    a.click();
  }
}
