import { Component, signal, computed, inject } from '@angular/core';
import { NgFor, NgIf, NgClass, DecimalPipe } from '@angular/common';
import { RouterLink } from '@angular/router';
import { DomSanitizer, SafeHtml } from '@angular/platform-browser';
import { SCENARIOS } from '../../data/scenarios';
import { EvaluationService, EvalResult, AgentResult } from '../../services/evaluation.service';
import { ModeService } from '../../services/mode.service';
import { AuditChainService } from '../../services/audit-chain.service';

@Component({
  selector: 'app-scenario-player',
  standalone: true,
  imports: [NgFor, NgIf, NgClass, RouterLink, DecimalPipe],
  templateUrl: './scenario-player.html',
  styleUrl: './scenario-player.css'
})
export class ScenarioPlayerComponent {
  private svc = inject(EvaluationService);
  private modeService = inject(ModeService);
  private san = inject(DomSanitizer);
  private chain = inject(AuditChainService);

  // ── Feature 3: Human-in-the-loop review state ──────────────────
  private reviewedCalls = signal<Map<string, 'approved'|'denied'>>(new Map());
  reviewDecision(callId: string, outcome: 'approved'|'denied') {
    this.reviewedCalls.update(m => { const n = new Map(m); n.set(callId, outcome); return n; });
  }
  reviewOutcome(callId: string): 'approved'|'denied'|null {
    return this.reviewedCalls().get(callId) ?? null;
  }

  // ── Feature 1: Highlight critical terms in explanation text ─────
  highlight(text: string): SafeHtml {
    if (!text) return this.san.bypassSecurityTrustHtml('');
    // Drug names, medical terms, key numbers
    const drugs = /\b(Ibuprofen|Aspirin|Naproxen|Paracetamol|Acetaminophen|Warfarin|Metoprolol|Verapamil|Azithromycin|Haloperidol|Ciprofloxacin|Lisinopril|Insulin|NSAIDs?|COX-1)\b/g;
    const conditions = /\b(AERD|contraindication|allergy|aspirin.allerg\w*|QT\s+prolongation|STEMI|hepatotoxic\w*|hypoglycemi\w*|bradycardia|anaphylactic)\b/gi;
    const numbers = /\b(0\.\d+|<\d+ms|\d+ms|\$[\d,]+|\d+%)\b/g;
    const decisions = /\b(DENIED|BLOCKED|ESCALATED|REDACTED|ALLOWED|FLAGGED|ALLOW|DENY|REDACT|ESCALATE|FLAG)\b/g;
    const policy  = /\b(PII Boundary|Scope Lock|Confidence Gate|Language Match|Terminology Lock|Script Guard|contraindication.check)\b/gi;

    let out = text
      .replace(drugs,      m => `<mark class="hl-drug">${m}</mark>`)
      .replace(conditions, m => `<mark class="hl-cond">${m}</mark>`)
      .replace(numbers,    m => `<mark class="hl-num">${m}</mark>`)
      .replace(decisions,  m => `<mark class="hl-decision">${m}</mark>`)
      .replace(policy,     m => `<mark class="hl-policy">${m}</mark>`);
    return this.san.bypassSecurityTrustHtml(out);
  }

  get shadowMode() { return !this.modeService.enforced(); }

  /** In shadow mode, interceptions are logged but not blocked — show ALLOW + near-miss indicator */
  shadowDecision(original: string): string {
    return this.shadowMode && ['DENY','ESCALATE','FLAG','REDACT'].includes(original) ? 'ALLOW' : original;
  }
  isShadowNearMiss(original: string): boolean {
    return this.shadowMode && ['DENY','ESCALATE','FLAG','REDACT'].includes(original);
  }
  get nearMissCount() {
    if (!this.shadowMode) return 0;
    return [...this.revealedCalls().values()].filter(r => ['DENY','ESCALATE','FLAG','REDACT'].includes(r.decision)).length;
  }
  get nearMissValue() { return this.nearMissCount * 2400; }

  categories = [
    {
      id: 'demo', label: '▶ Demo',
      scenarios: [
        // v3 video flow: Luganda (1-call contraindication DENY) then Acholi (1-call unsupported-language ESCALATE)
        SCENARIOS.find(s => s.id === 'luganda-aspirin-demo')!,
        SCENARIOS.find(s => s.id === 'acholi-degradation')!,
      ]
    },
    {
      id: 'clinical', label: '🏥 Clinical Safety',
      scenarios: [
        SCENARIOS.find(s => s.id === 'contraindication')!,
        SCENARIOS.find(s => s.id === 'clinical-pii')!,
        SCENARIOS.find(s => s.id === 'scope-violation')!,
        SCENARIOS.find(s => s.id === 'low-confidence')!,
        SCENARIOS.find(s => s.id === 'stemi-exception')!,
      ]
    },
    {
      id: 'lingua', label: '🌍 Lingua · 8 Languages',
      scenarios: [
        SCENARIOS.find(s => s.id === 'luganda-mismatch')!,
        SCENARIOS.find(s => s.id === 'lingua-mismatch')!,
        SCENARIOS.find(s => s.id === 'lingua-degradation')!,
        SCENARIOS.find(s => s.id === 'tagalog-terminology')!,
        SCENARIOS.find(s => s.id === 'amharic-script-guard')!,
      ]
    },
    {
      id: 'pharma', label: '💊 Drug Safety',
      scenarios: [
        SCENARIOS.find(s => s.id === 'multihop-warfarin')!,
        SCENARIOS.find(s => s.id === 'dose-toxicity')!,
        SCENARIOS.find(s => s.id === 'qt-prolongation')!,
      ]
    },
    {
      id: 'video', label: '🎬 More Cases',
      scenarios: [
        SCENARIOS.find(s => s.id === 'luganda-contraindication')!,
        SCENARIOS.find(s => s.id === 'luganda-pediatric-pii')!,
      ]
    },
    {
      id: 'agent', label: '🤖 Try It Yourself',
      scenarios: [],
    },
  ];

  activeCategory = signal(0);
  get scenarios() { return this.categories[this.activeCategory()].scenarios; }

  // ── Live Agent signals ───────────────────────────────────────
  agentPatient = signal('');
  agentLanguage = signal('en');
  agentResult = signal<AgentResult | null>(null);
  agentRunning = signal(false);

  async runAgent() {
    if (!this.agentPatient() || this.agentRunning()) return;
    this.agentRunning.set(true);
    this.agentResult.set(null);
    try {
      const result = await this.svc.runAgent(this.agentPatient(), this.agentLanguage());
      this.agentResult.set(result);
    } catch (e) {
      console.error('Agent run failed', e);
    } finally {
      this.agentRunning.set(false);
    }
  }

  selectCategory(idx: number) {
    this.activeCategory.set(idx);
    this.activeScenarioIdx.set(0);
    this.reset();
  }

  activeScenarioIdx = signal(0);
  revealedCalls = signal<Map<string, EvalResult>>(new Map());
  evaluatingCallId = signal<string | null>(null);
  expandedCall = signal<string | null>(null);
  playing = signal(false);
  done = signal(false);
  backendLive = signal<boolean | null>(null);
  gemmaLoaded = signal(false);
  modelLoading = signal(false);
  transcription = signal<string | null>(null);
  transcriptionTokens = signal<number>(0);
  /** Index of the next call to fire (0 = first). Manual step-by-step mode. */
  currentCallIdx = signal(0);

  private playToken = 0;
  private detailSet = signal<Set<string>>(new Set());

  hasMoreCalls = computed(() => {
    const sc = this.activeScenario();
    return sc ? this.currentCallIdx() < sc.steps[0].toolCalls.length : false;
  });

  /** Friendly label for the next call to fire — shown on the main run button. */
  nextCallLabel = computed(() => {
    const sc = this.activeScenario();
    if (!sc) return '';
    const idx = this.currentCallIdx();
    const calls = sc.steps[0].toolCalls;
    if (idx === 0) return '▶ Run Tool Guard';
    if (idx >= calls.length) return '↻ Run Again';
    // Mid-scenario: describe what the agent is doing next
    return `▶ Send agent's next retry (${idx + 1} of ${calls.length})`;
  });

  isAgentTab = computed(() => this.activeCategory() === 5);
  anyInterceptDecision(): boolean {
    const intercept = new Set(['DENY', 'ESCALATE', 'FLAG', 'REDACT']);
    for (const r of this.revealedCalls().values()) {
      if (intercept.has(r.decision)) return true;
    }
    return false;
  }
  activeScenario = computed(() => this.scenarios[this.activeScenarioIdx()] ?? null);
  totalCalls = computed(() => this.activeScenario()?.steps[0]?.toolCalls?.length ?? 0);
  get currentStep() { return this.activeScenario()?.steps[0]; }

  async ngOnInit() {
    const health = await this.svc.getHealth();
    if (health) {
      this.backendLive.set(true);
      this.gemmaLoaded.set(health.gemma_loaded);
      if (!health.gemma_loaded) {
        this.modelLoading.set(true);
        this.svc.loadGemma()
          .then(() => { this.gemmaLoaded.set(true); this.modelLoading.set(false); this.warmInference(); })
          .catch(() => { this.modelLoading.set(false); });
      } else {
        this.warmInference();
      }
    } else {
      this.backendLive.set(false);
    }
  }

  /** Fire a tiny HYBRID eval on page load so the first real demo call is fast. */
  private warmInference() {
    this.svc.evaluate('recommend_care_pathway',
      { recommendation: 'Paracetamol 500mg for headache', patient_allergies: 'none' },
      { patient: 'warm-up' },
      { confidence: 1.0, inputLang: 'en', outputLang: 'en' }
    ).catch(() => {});
  }

  async loadGemma() {
    this.modelLoading.set(true);
    try {
      await this.svc.loadGemma();
      this.gemmaLoaded.set(true);
    } finally {
      this.modelLoading.set(false);
    }
  }

  async unloadGemma() {
    this.modelLoading.set(true);
    try {
      await this.svc.unloadGemma();
      this.gemmaLoaded.set(false);
    } finally {
      this.modelLoading.set(false);
    }
  }

  selectScenario(idx: number) {
    this.activeScenarioIdx.set(idx);
    this.reset();
  }

  reset() {
    this.playToken++;
    this.playing.set(false);
    this.revealedCalls.set(new Map());
    this.evaluatingCallId.set(null);
    this.expandedCall.set(null);
    this.detailSet.set(new Set());
    this.done.set(false);
    this.transcription.set(null);
    this.transcriptionTokens.set(0);
    this.currentCallIdx.set(0);
  }

  toggleDetail(id: string) {
    this.detailSet.update(s => {
      const n = new Set(s);
      n.has(id) ? n.delete(id) : n.add(id);
      return n;
    });
  }
  isDetailExpanded(id: string) { return this.detailSet().has(id); }

  /** Evaluate a single tool call (live or scripted). Returns null if play token expired. */
  private async evaluateOne(call: any, scenario: any, step: any, live: boolean, token: number): Promise<EvalResult | null> {
    if (call.evalPath === 'HYBRID') {
      this.evaluatingCallId.set(call.id);
    }
    let result: EvalResult;
    if (live) {
      const enrichedCtx = {
        patient: scenario.patient,
        ...Object.fromEntries(Object.entries(call.params)),
        patient_allergies: call.params['patient_allergies'] ?? '',
        current_medications: call.params['current_medications'] ?? '',
        patient_conditions: call.params['patient_conditions'] ?? '',
      };
      result = await this.svc.evaluate(call.tool, call.params, enrichedCtx, {
        confidence: parseFloat(call.params['confidence'] ?? '1.0'),
        inputLang: step.language,
        outputLang: call.params['output_language'] ?? step.language,
      });
    } else {
      const delay = call.evalPath === 'HYBRID' ? 1800 : 280;
      await new Promise(r => setTimeout(r, delay));
      if (this.playToken !== token) { this.evaluatingCallId.set(null); return null; }
      result = {
        decision: call.decision,
        eval_path: call.evalPath,
        policy_triggered: call.explanation.policyTriggered,
        latency_ms: call.latencyMs,
        explanation: call.explanation.summary,
        reasoning: call.explanation.reasoning,
        why_hybrid: call.explanation.whyHybrid ?? '',
        redacted_fields: call.redactedFields ?? [],
        translated_response: call.explanation.translatedResponse ?? '',
        tokens_used: call.evalPath === 'HYBRID' ? 312 : 0,
        hmac: `scripted_no_hmac`,
        hash: await this.svc.sha256(`${call.id}:${call.decision}:${call.latencyMs}`),
        timestamp: new Date().toISOString(),
      };
    }
    if (this.playToken !== token) { this.evaluatingCallId.set(null); return null; }
    this.evaluatingCallId.set(null);
    this.revealedCalls.update(m => { const n = new Map(m); n.set(call.id, result); return n; });
    // Fire-and-forget the chain append — don't block UI on SHA-256 hashing
    this.chain.append(result, {
      tool: call.tool,
      modality: step.inputType,
      language: step.language,
      scenario: scenario.title,
    }).catch(() => {});
    return result;
  }

  /** Re-fire a single check against the live backend — for demo drill-down on one decision. */
  async replayCall(call: any) {
    if (this.playing()) return;
    const token = ++this.playToken;
    this.playing.set(true);
    // Clear this card so the user sees it re-animate
    this.revealedCalls.update(m => { const n = new Map(m); n.delete(call.id); return n; });
    const live = await this.svc.checkBackend();
    this.backendLive.set(live);
    const step = this.activeScenario().steps[0];
    const scenario = this.activeScenario();
    await this.evaluateOne(call, scenario, step, live, token);
    if (this.playToken === token) {
      this.playing.set(false);
      // Re-expand this card so the user sees the new details
      this.expandedCall.set(call.id);
      if (!this.detailSet().has(call.id)) {
        this.detailSet.update(s => { const n = new Set(s); n.add(call.id); return n; });
      }
    }
  }

  /** True if this call has a blocked decision AND a later call exists in the scenario.
   *  Stays true even after the later call has fired — so the button doesn't vanish. */
  canBypass(call: any): boolean {
    const r = this.revealedCalls().get(call.id);
    if (!r) return false;
    if (!['DENY','ESCALATE','FLAG','REDACT'].includes(r.decision)) return false;
    const sc = this.activeScenario();
    if (!sc) return false;
    const calls = sc.steps[0].toolCalls;
    const callIdx = calls.findIndex((c: any) => c.id === call.id);
    return callIdx >= 0 && callIdx < calls.length - 1;
  }

  /** Demo-only bypass. Fires the next un-fired call; if all calls fired, re-fires the last one. */
  async bypassAndAdvance() {
    if (this.playing()) return;
    if (this.hasMoreCalls()) {
      await this.play();
      return;
    }
    // Everything fired — replay the last call (re-shows the next intercept Gemma catches)
    const sc = this.activeScenario();
    if (!sc) return;
    const calls = sc.steps[0].toolCalls;
    await this.replayCall(calls[calls.length - 1]);
  }

  /** Fire ONE call at a time. First click runs Call 1; subsequent clicks run Call N+1. */
  async play() {
    const sc = this.activeScenario();
    if (!sc) return;
    const calls = sc.steps[0].toolCalls;
    const idx = this.currentCallIdx();

    // All calls done — clicking the button now means "reset and start over"
    if (idx >= calls.length) {
      this.reset();
      return;
    }

    const token = ++this.playToken;
    this.playing.set(true);
    this.done.set(false);

    const live = await this.svc.checkBackend();
    this.backendLive.set(live);

    const step = sc.steps[0];

    // Fire transcription only on the FIRST call (patient utterance is the same throughout).
    if (idx === 0 && live && step.inputType === 'audio' && step.language !== 'en') {
      const text = step.inputPreview;
      const first = text.indexOf('"');
      const last = text.lastIndexOf('"');
      if (first >= 0 && last > first) {
        const raw = text.substring(first + 1, last)
          .replace(/\n/g, ' ')
          .replace(/\s+/g, ' ')
          .trim();
        this.transcription.set('…');
        this.svc.transcribe(raw, step.language).then(r => {
          if (r.transcription) {
            this.transcription.set(r.transcription);
            this.transcriptionTokens.set(r.tokens_used);
          } else {
            this.transcription.set(null);
          }
        });
      }
    }

    const call = calls[idx];
    const result = await this.evaluateOne(call, sc, step, live, token);
    if (result === null || this.playToken !== token) return;

    // Auto-expand the call we just ran
    this.expandedCall.set(call.id);

    // Advance index. If that was the last call, mark done.
    this.currentCallIdx.set(idx + 1);
    this.playing.set(false);
    if (idx + 1 >= calls.length) {
      this.done.set(true);
    }
  }

  toggleExpand(id: string) {
    this.expandedCall.update(v => v === id ? null : id);
  }

  isRevealed(id: string) { return this.revealedCalls().has(id); }
  isExpanded(id: string) { return this.expandedCall() === id; }
  getResult(id: string) { return this.revealedCalls().get(id); }

  // Returns live result if available, else synthesises from scripted data so
  // the detail panel always renders regardless of backend availability
  getDisplayResult(call: any): any {
    const live = this.revealedCalls().get(call.id);
    if (live) return live;
    // Scripted fallback — convert call.explanation to EvalResult shape
    return {
      decision: call.decision,
      eval_path: call.evalPath,
      policy_triggered: call.explanation.policyTriggered,
      latency_ms: call.latencyMs,
      explanation: call.explanation.summary,
      reasoning: call.explanation.reasoning,
      why_hybrid: call.explanation.whyHybrid ?? '',
      redacted_fields: call.redactedFields ?? [],
      hmac: `hmac_${call.id}_scripted`,
      hash: 'demo_' + call.id.replace(/-/g, '').padEnd(60, '0'),
      timestamp: new Date().toISOString(),
      _isScripted: true,
    };
  }

  get allowCount() {
    return [...this.revealedCalls().values()].filter(r => r.decision === 'ALLOW').length;
  }
  get interceptCount() {
    return [...this.revealedCalls().values()].filter(r => r.decision !== 'ALLOW').length;
  }

  decisionClass(d: string) {
    return { allow: d==='ALLOW', deny: d==='DENY', redact: d==='REDACT', escalate: d==='ESCALATE', flag: d==='FLAG' };
  }
  decisionIcon(d: string) {
    return ({ALLOW:'✓',DENY:'✕',REDACT:'⬡',ESCALATE:'↑',FLAG:'⚑'} as Record<string,string>)[d] ?? '?';
  }
  langLabel(code: string) {
    return ({sw:'Swahili',hi:'Hindi',ar:'Arabic (RTL)',bn:'Bengali',tl:'Tagalog',qu:'Quechua',am:'Amharic',lg:'Luganda',ach:'Acholi'} as Record<string,string>)[code] ?? code;
  }

  // Audit records produced by this run only — no reference to pre-built chain
  get auditTrailRecords() {
    return (this.currentStep?.toolCalls ?? [])
      .filter((call: any) => this.revealedCalls().has(call.id))
      .map(call => {
        const r = this.revealedCalls().get(call.id)!;
        return { tool: call.tool, decision: r.decision, eval_path: r.eval_path,
          latency_ms: r.latency_ms, policy_triggered: r.policy_triggered,
          hash: r.hash, hmac: r.hmac, timestamp: r.timestamp };
      });
  }

  fmtTime(iso: string): string {
    try { return new Date(iso).toLocaleTimeString('en', {hour12: false}); } catch { return ''; }
  }

  // Convert PMC IDs and known regulatory references to clickable links
  linkifySource(text: string): SafeHtml {
    const DOC_URLS: Record<string, string> = {
      'PMC3005316':  'https://pmc.ncbi.nlm.nih.gov/articles/PMC3005316/',
      'PMC8817602':  'https://pmc.ncbi.nlm.nih.gov/articles/PMC8817602/',
      'PMC8743870':  'https://pmc.ncbi.nlm.nih.gov/articles/PMC8743870/',
      'PMC11729812': 'https://pmc.ncbi.nlm.nih.gov/articles/PMC11729812/',
      'PMC12712589': 'https://pmc.ncbi.nlm.nih.gov/articles/PMC12712589/',
      'PMC2723735':  'https://pmc.ncbi.nlm.nih.gov/articles/PMC2723735/',
    };
    let out = text
      .replace(/PMC\d+/g, m => DOC_URLS[m]
        ? `<a href="${DOC_URLS[m]}" target="_blank" rel="noopener" class="src-link">${m}</a>` : m)
      .replace(/45 CFR 164\.502\(b\)/g,
        '<a href="https://www.law.cornell.edu/cfr/text/45/164.502" target="_blank" rel="noopener" class="src-link">45 CFR 164.502(b)</a>')
      .replace(/WHO Malaria Guidelines 2023/g,
        '<a href="https://www.who.int/publications/i/item/guidelines-for-malaria" target="_blank" rel="noopener" class="src-link">WHO Malaria Guidelines 2023</a>')
      .replace(/ACC\/AHA STEMI Guidelines 2013/g,
        '<a href="https://www.ahajournals.org/doi/10.1161/CIR.0b013e3182742cf6" target="_blank" rel="noopener" class="src-link">ACC/AHA STEMI Guidelines 2013</a>');
    return this.san.bypassSecurityTrustHtml(out);
  }
}
