import { Routes } from '@angular/router';
import { authGuard } from './core/auth/guards/auth.guard';
import { roleGuard } from './core/auth/guards/role.guard';
import { hasKeysGuard } from './core/auth/guards/has-keys.guard';

export const routes: Routes = [
  {
    path: '',
    pathMatch: 'full',
    title: 'Login · Logos',
    loadComponent: () => import('./core/auth/pages/login/login').then(m => m.Login),
  },
  {
    path: '',
    canActivate: [authGuard],
    loadComponent: () => import('./core/layout/shell/shell').then(m => m.Shell),
    children: [
      { path: 'dashboard',       title: 'Dashboard · Logos',       data: { roles: ['logos_admin'] },                canActivate: [roleGuard], loadComponent: () => import('./features/dashboard/dashboard').then(m => m.Dashboard) },
      { path: 'statistics',      title: 'Statistics · Logos',      data: { roles: ['logos_admin'] },                canActivate: [roleGuard], loadComponent: () => import('./features/statistics/statistics').then(m => m.Statistics) },
      { path: 'models',         title: 'Models · Logos',           data: { roles: ['logos_admin'] },                canActivate: [roleGuard], loadComponent: () => import('./features/models/models').then(m => m.Models) },
      { path: 'models/:id/errors', title: 'Model Error Report · Logos', data: { roles: ['logos_admin'] },           canActivate: [roleGuard], loadComponent: () => import('./features/model-error-report/model-error-report').then(m => m.ModelErrorReport) },
      { path: 'providers',      title: 'Providers · Logos',        data: { roles: ['logos_admin'] },                canActivate: [roleGuard], loadComponent: () => import('./features/providers/providers').then(m => m.Providers) },
      { path: 'policies',       title: 'Policies · Logos',         data: { roles: ['logos_admin'] },                canActivate: [roleGuard], loadComponent: () => import('./features/policies/policies').then(m => m.Policies) },
      { path: 'billing',        title: 'Billing · Logos',          data: { roles: ['logos_admin'] },                canActivate: [roleGuard], loadComponent: () => import('./features/billing/billing').then(m => m.Billing) },
      { path: 'user-management', title: 'Users · Logos',           data: { roles: ['logos_admin', 'app_admin'] },   canActivate: [roleGuard], loadComponent: () => import('./features/user-management/user-management').then(m => m.UserManagement) },
      { path: 'team-management', title: 'Teams · Logos',           data: { roles: ['logos_admin', 'app_admin'] },   canActivate: [roleGuard], loadComponent: () => import('./features/team-management/team-management').then(m => m.TeamManagement) },
      { path: 'teams/:id',       title: 'Team · Logos',            data: { roles: ['logos_admin', 'app_admin'] },   canActivate: [roleGuard], loadComponent: () => import('./features/team-detail/team-detail').then(m => m.TeamDetail) },
      { path: 'my-workspace',    title: 'My Workspace · Logos',    canActivate: [hasKeysGuard], loadComponent: () => import('./features/my-workspace/my-workspace').then(m => m.MyWorkspace) },
      { path: 'open-code',       title: 'OpenCode · Logos',        canActivate: [hasKeysGuard], loadComponent: () => import('./features/open-code/open-code').then(m => m.OpenCode) },
      { path: 'claude-code',     title: 'Claude Code · Logos',     canActivate: [hasKeysGuard], loadComponent: () => import('./features/claude-code/claude-code').then(m => m.ClaudeCode) },
      { path: 'no-access',       title: 'No Access · Logos',       loadComponent: () => import('./features/no-access/no-access').then(m => m.NoAccess) },
      { path: '**', redirectTo: 'my-workspace' },
    ],
  },
];
