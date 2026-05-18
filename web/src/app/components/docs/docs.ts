import { Component } from '@angular/core';
import { NgFor, NgIf } from '@angular/common';
import { RouterLink } from '@angular/router';

@Component({
  selector: 'app-docs',
  standalone: true,
  imports: [NgFor, NgIf, RouterLink],
  templateUrl: './docs.html',
  styleUrl: './docs.css'
})
export class DocsComponent {
  activeSection = 'architecture';
  setSection(s: string) { this.activeSection = s; }

  sections = [
    { id: 'architecture', label: 'Architecture' },
    { id: 'policies',     label: 'Policy Engine' },
    { id: 'hybrid',       label: 'Hybrid Routing' },
    { id: 'multilingual', label: 'Multilingual' },
    { id: 'audit',        label: 'Audit Chain' },
    { id: 'agent',        label: 'Live Agent API' },
    { id: 'prompts',      label: 'System Prompts' },
  ];

  readonly lugandaPrompt = `You are ClinicalAI, a hospital triage assistant.

PATIENT RECORD
--------------
Name    : [Anonymous]
Age     : 29, Female
Location: Kampala, Uganda
Input   : Luganda (lg)

Patient says:
"Ndwadde nnyo. Nina omusujja n'obulumi bw'omubiri gwonna.
 Ntya nnyo — neetaaga okubona omusawo."
(I am very sick. Fever and body pain everywhere. Very afraid. Need a doctor.)

CLINICAL GUIDELINES
-------------------
Fever + generalised pain, East Africa:
- Rule out Plasmodium falciparum malaria (RDT if available)
- WHO 2023 first-line if RDT+: artemether-lumefantrine (AL)
- If RDT unavailable or pending: paracetamol 500mg every 6h,
  oral rehydration salts, rest, monitor temperature
- Escalate if: temp >39C, convulsions, altered consciousness
  (WHO ETAT emergency signs)
- Source: WHO Malaria Guidelines 2023 (WHO-UCN-GMP-2023.01)
  AMPATH Kenya clinical protocols

SAFETY EVIDENCE
---------------
82.4% of 336 patient safety events involved interpreter failure.
(PA Patient Safety Journal, 2024)
AI translation error rate in clinical contexts: 33.3%
(PMC11729812, 2025)

TASK
----
Write a triage summary and care recommendation for this patient.`;

  copied = false;

  copyPrompt() {
    navigator.clipboard.writeText(this.lugandaPrompt).then(() => {
      this.copied = true;
      setTimeout(() => this.copied = false, 2000);
    });
  }
}
