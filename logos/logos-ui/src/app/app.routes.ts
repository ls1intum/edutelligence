import { Routes } from '@angular/router';

export const routes: Routes = [
  {
    path: '',
    loadComponent: () => import('./core/auth/pages/login/login').then(m => m.Login),
  },
  {
    path: '',
    loadComponent: () => import('./core/layout/shell/shell').then(m => m.Shell),
    children: [
      { path: 'dashboard',       loadComponent: () => import('./features/dashboard/dashboard').then(m => m.Dashboard) },
      { path: 'statistics',      loadComponent: () => import('./features/statistics/statistics').then(m => m.Statistics) },
      { path: 'models',          loadComponent: () => import('./features/models/models').then(m => m.Models) },
      { path: 'providers',       loadComponent: () => import('./features/providers/providers').then(m => m.Providers) },
      { path: 'policies',        loadComponent: () => import('./features/policies/policies').then(m => m.Policies) },
      { path: 'billing',         loadComponent: () => import('./features/billing/billing').then(m => m.Billing) },
      { path: 'user-management', loadComponent: () => import('./features/user-management/user-management').then(m => m.UserManagement) },
      { path: 'team-management', loadComponent: () => import('./features/team-management/team-management').then(m => m.TeamManagement) },
      { path: 'my-workspace',    loadComponent: () => import('./features/my-workspace/my-workspace').then(m => m.MyWorkspace) },
      { path: 'my-keys',         loadComponent: () => import('./features/my-keys/my-keys').then(m => m.MyKeys) },
      { path: 'open-code',       loadComponent: () => import('./features/open-code/open-code').then(m => m.OpenCode) },
      { path: 'settings',        loadComponent: () => import('./features/settings/settings').then(m => m.Settings) },
      { path: '**', redirectTo: 'dashboard' },
    ],
  },
];
