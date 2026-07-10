import { Component, computed, inject, signal, ChangeDetectionStrategy } from '@angular/core';
import { Router, RouterModule } from '@angular/router';
import { AuthService } from '../../auth/services/auth.service';
import { MENU_ITEMS, NAV_GROUP_LABELS } from '../../../shared/constants/nav-items';
import { MenuItem } from '../../../shared/models/nav.model';
import { UserRole } from '../../auth/models/user.model';
import { Logo } from '../../../shared/components/logo/logo';
import { ThemeToggle } from '../../../shared/components/theme-toggle/theme-toggle';
import { Orbs } from '../../../shared/components/orbs/orbs';
import { IconTileComponent } from '../../../shared/components/icon-tile/icon-tile';
import { MyKeysService } from '../../services/my-keys.service';

interface NavSection {
  label: string;
  items: MenuItem[];
}

@Component({
  selector: 'app-shell',
  standalone: true,
  imports: [RouterModule, Logo, ThemeToggle, Orbs, IconTileComponent],
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

  /** null while unresolved; treated as hidden until proven, failing closed like hasKeysGuard. */
  hasKeys = signal<boolean | null>(null);

  constructor() {
    this.router.events.subscribe(() => {
      this.closeSidebar();
    });
    this.keysService
      .getMyKeys()
      .then((keys) => this.hasKeys.set(keys.length > 0))
      .catch(() => this.hasKeys.set(false));
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

  userInitials = computed(() => {
    const name = this.auth.currentUser()?.username ?? '';
    const parts = name.trim().split(/\s+/);
    if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    return name.slice(0, 2).toUpperCase();
  });

  navSections = computed<NavSection[]>(() => {
    const role = this.auth.role();
    if (!role) return [];
    const keyGatedPaths = ['/my-workspace', '/open-code'];
    // Keys can outlive team membership (orphaned key after removal), so both
    // must hold; this mirrors hasKeysGuard, which is the actual access boundary.
    const hasTeams = (this.auth.currentUser()?.teams.length ?? 0) > 0;
    const showKeyGated = hasTeams && this.hasKeys() === true;
    const visible = MENU_ITEMS.filter(
      (item) =>
        item.roles.includes(role as UserRole) &&
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
