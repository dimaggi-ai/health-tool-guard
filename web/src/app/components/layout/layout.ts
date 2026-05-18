import { Component, inject, signal, OnInit } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { NgIf } from '@angular/common';
import { ModeService } from '../../services/mode.service';
import { EvaluationService } from '../../services/evaluation.service';

@Component({
  selector: 'app-layout',
  standalone: true,
  imports: [RouterLink, RouterLinkActive, RouterOutlet, NgIf],
  templateUrl: './layout.html',
  styleUrl: './layout.css'
})
export class LayoutComponent implements OnInit {
  mode      = inject(ModeService);
  private svc = inject(EvaluationService);
  collapsed = signal(false);

  /**
   * Demo-mode banner state.
   *  - `null`  → initial check in flight (don't render)
   *  - `true`  → backend reachable, hide banner
   *  - `false` → backend offline; show banner explaining scripted-fallback mode
   */
  backendLive = signal<boolean | null>(null);

  get enforcementMode() { return this.mode.enforced(); }
  setMode(enforced: boolean) { this.mode.enforced.set(enforced); }
  toggleSidebar() { this.collapsed.update(v => !v); }

  async ngOnInit() {
    const live = await this.svc.checkBackend();
    this.backendLive.set(live);
  }
}
