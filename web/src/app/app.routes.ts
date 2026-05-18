import { Routes } from '@angular/router';
import { LayoutComponent } from './components/layout/layout';

export const routes: Routes = [
  {
    path: '',
    component: LayoutComponent,
    children: [
      { path: '', redirectTo: 'overview', pathMatch: 'full' },
      { path: 'overview', loadComponent: () => import('./components/ceo-overview/ceo-overview').then(m => m.CeoOverviewComponent) },
      { path: 'demo',     loadComponent: () => import('./components/scenario-player/scenario-player').then(m => m.ScenarioPlayerComponent) },
      { path: 'policies', loadComponent: () => import('./components/policy-dashboard/policy-dashboard').then(m => m.PolicyDashboardComponent) },
      { path: 'audit',    loadComponent: () => import('./components/audit-chain/audit-chain').then(m => m.AuditChainComponent) },
      { path: 'architecture', loadComponent: () => import('./components/architecture/architecture').then(m => m.ArchitectureComponent) },
      { path: 'showcase', redirectTo: 'overview' },
      { path: 'docs',     loadComponent: () => import('./components/docs/docs').then(m => m.DocsComponent) },
    ]
  },
  { path: '**', redirectTo: 'overview' },
];
