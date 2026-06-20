import { Routes } from '@angular/router';
import { authGuard } from './core/auth/guards/auth.guard';
import { roleGuard } from './core/auth/guards/role.guard';

export const routes: Routes = [
  {
    path: '',
    pathMatch: 'full',
    loadComponent: () => import('./core/auth/pages/login/login').then(m => m.Login),
  },
  {
    path: '',
    canActivate: [authGuard],
    loadComponent: () => import('./core/layout/shell/shell').then(m => m.Shell),
    children: [
      { path: 'dashboard',       data: { roles: ['logos_admin'] },                canActivate: [roleGuard], loadComponent: () => import('./features/dashboard/dashboard').then(m => m.Dashboard) },
      { path: 'statistics',      data: { roles: ['logos_admin'] },                canActivate: [roleGuard], loadComponent: () => import('./features/statistics/statistics').then(m => m.Statistics) },
      { path: 'models',          data: { roles: ['logos_admin'] },                canActivate: [roleGuard], loadComponent: () => import('./features/models/models').then(m => m.Models) },
      { path: 'providers',       data: { roles: ['logos_admin'] },                canActivate: [roleGuard], loadComponent: () => import('./features/providers/providers').then(m => m.Providers) },
      { path: 'policies',        data: { roles: ['logos_admin'] },                canActivate: [roleGuard], loadComponent: () => import('./features/policies/policies').then(m => m.Policies) },
      { path: 'billing',         data: { roles: ['logos_admin'] },                canActivate: [roleGuard], loadComponent: () => import('./features/billing/billing').then(m => m.Billing) },
      { path: 'user-management', data: { roles: ['logos_admin', 'app_admin'] },   canActivate: [roleGuard], loadComponent: () => import('./features/user-management/user-management').then(m => m.UserManagement) },
      { path: 'team-management', data: { roles: ['logos_admin', 'app_admin'] },   canActivate: [roleGuard], loadComponent: () => import('./features/team-management/team-management').then(m => m.TeamManagement) },
      { path: 'teams/:id',       data: { roles: ['logos_admin', 'app_admin'] },   canActivate: [roleGuard], loadComponent: () => import('./features/team-detail/team-detail').then(m => m.TeamDetail) },
      { path: 'my-teams',        loadComponent: () => import('./features/my-teams/my-teams').then(m => m.MyTeams) },
      { path: 'my-keys',         loadComponent: () => import('./features/my-keys/my-keys').then(m => m.MyKeys) },
      { path: 'open-code',       loadComponent: () => import('./features/open-code/open-code').then(m => m.OpenCode) },
      { path: '**', redirectTo: 'my-teams' },
    ],
  },
];
