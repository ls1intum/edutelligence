import { Component, computed, inject, signal, ChangeDetectionStrategy } from '@angular/core';
import { Router, RouterModule } from '@angular/router';
import { AuthService } from '../../auth/services/auth.service';
import { MENU_ITEMS, NAV_GROUP_LABELS } from '../../../shared/constants/nav-items';
import { MenuItem } from '../../../shared/models/nav.model';
import { UserRole } from '../../auth/models/user.model';
import { Logo } from '../../../shared/components/logo/logo';
import { ThemeToggle } from '../../../shared/components/theme-toggle/theme-toggle';
import { IconTileComponent } from '../../../shared/components/icon-tile/icon-tile';
import { MyKeysService } from '../../services/my-keys.service';

interface NavSection {
  label: string;
  items: MenuItem[];
}

@Component({
  selector: 'app-shell',
  standalone: true,
  imports: [RouterModule, Logo, ThemeToggle, IconTileComponent],
  templateUrl: './shell.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './shell.scss',
})
export class Shell {
  auth = inject(AuthService);
  private router = inject(Router);
  private keysService = inject(MyKeysService);

  isOpen = signal(false);
  showLogoutModal = signal(false);
  private opener: HTMLElement | null = null;

  /**
   * Shared with hasKeysGuard (see MyKeysService.hasKeys) so the guard reads
   * an already-resolved value on repeat navigations instead of re-fetching.
   */
  hasKeys = this.keysService.hasKeys;

  /**
   * Whether the agent runner is running on this deployment. The runner is
   * opt-in per deployment (a compose profile), so where it is not selected
   * there is no /api/agent router at all: the probe below falls through to
   * the SPA and comes back with its HTML shell instead of the runner's JSON
   * health answer. Only that JSON answer means the runner is really there,
   * and it is what keeps the menu entry out of deployments without agents.
   * Hidden by default: while the probe is in flight, and on any failure,
   * the entry stays out rather than pointing at a service that is not up.
   */
  agentAvailable = signal(false);

  constructor() {
    this.router.events.subscribe(() => {
      this.closeSidebar();
    });
    void this.probeAgent();
  }

  /**
   * One probe per page load: the absence of the entry is the default, and a
   * deployment that enables the runner later picks it up on the next reload.
   * The endpoint needs no token, so a raw fetch keeps this out of the
   * auth-intercepted HttpClient.
   */
  async probeAgent(): Promise<void> {
    try {
      const res = await fetch('/api/agent/health', { cache: 'no-store' });
      const type = res.headers.get('content-type') ?? '';
      this.agentAvailable.set(res.ok && type.includes('application/json'));
    } catch {
      this.agentAvailable.set(false);
    }
  }

  toggleSidebar() {
    this.isOpen.update((open) => !open);
  }

  closeSidebar() {
    this.isOpen.set(false);
  }

  openLogoutModal() {
    this.opener = document.activeElement as HTMLElement;
    this.showLogoutModal.set(true);
    setTimeout(() => {
      document.querySelector<HTMLElement>('.btn-cancel')?.focus();
    }, 0);
  }

  closeLogoutModal() {
    this.showLogoutModal.set(false);
    setTimeout(() => this.opener?.focus(), 0);
  }

  confirmLogout() {
    this.auth.logout();
    this.router.navigate(['/']);
  }

  fullName = computed(() => {
    const user = this.auth.currentUser();
    if (!user) return '';
    const full = `${user.prename ?? ''} ${user.name ?? ''}`.trim();
    return full || user.username;
  });

  userInitials = computed(() => {
    const user = this.auth.currentUser();
    if (!user) return '';
    const first = (user.prename ?? '').trim();
    const last = (user.name ?? '').trim();
    if (first && last) return (first[0] + last[0]).toUpperCase();
    return (first || last || user.username).slice(0, 2).toUpperCase();
  });

  navSections = computed<NavSection[]>(() => {
    const role = this.auth.role();
    if (!role) return [];
    const keyGatedPaths = ['/my-workspace', '/ai-tools'];
    // Keys can outlive team membership (orphaned key after removal), so both
    // must hold; this mirrors hasKeysGuard, which is the actual access boundary.
    const hasTeams = (this.auth.currentUser()?.teams.length ?? 0) > 0;
    const showKeyGated = hasTeams && this.hasKeys() === true;
    const visible = MENU_ITEMS.filter(
      (item) =>
        item.roles.includes(role as UserRole) &&
        (!item.requiresAgent || this.agentAvailable()) &&
        (!keyGatedPaths.includes(item.path) || showKeyGated),
    );
    return (['system', 'management', 'personal'] as const)
      .map((key) => ({
        label: NAV_GROUP_LABELS[key],
        items: visible.filter((i) => i.group === key),
      }))
      .filter((g) => g.items.length > 0);
  });
}
