import { Injectable, signal } from '@angular/core';

@Injectable({ providedIn: 'root' })
export class ModeService {
  enforced = signal(true);
  toggle() { this.enforced.update(v => !v); }
}
