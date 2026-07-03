import {
  Component,
  computed,
  effect,
  inject,
  signal,
  OnInit,
  ChangeDetectionStrategy,
} from '@angular/core';
import { ActivatedRoute, Router, RouterModule } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { ModalFormComponent } from '../../shared/components/modal/modal-form/modal-form';
import { AuthService } from '../../core/auth/services/auth.service';
import { TeamManagementService } from '../../core/services/team-management.service';
import {
  TeamDetail as TeamDetailModel,
  TeamMember,
  TeamApiKey,
  TeamModelPermission,
} from '../../shared/models/team.model';

import { OverviewTabComponent } from './tabs/overview/overview-tab';
import { MembersTabComponent } from './tabs/members/members-tab';
import { AppKeysTabComponent } from './tabs/app-keys/app-keys-tab';
import { ProvidersTabComponent } from './tabs/providers/providers-tab';
import { ModelsTabComponent } from './tabs/models/models-tab';
import { SettingsTabComponent } from './tabs/settings/settings-tab';
import { BillingTabComponent } from './tabs/billing/billing-tab';
import { ErrorMessageComponent } from '../../shared/components/error-message/error-message';

export type Tab =
  | 'overview'
  | 'members'
  | 'application_keys'
  | 'providers'
  | 'models'
  | 'settings'
  | 'billing';

@Component({
  selector: 'app-team-detail',
  standalone: true,
  imports: [
    FormsModule,
    RouterModule,
    ModalFormComponent,
    ErrorMessageComponent,
    OverviewTabComponent,
    MembersTabComponent,
    AppKeysTabComponent,
    ProvidersTabComponent,
    ModelsTabComponent,
    SettingsTabComponent,
    BillingTabComponent,
  ],
  templateUrl: './team-detail.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './team-detail.scss',
})
export class TeamDetail implements OnInit {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private auth = inject(AuthService);
  private teamService = inject(TeamManagementService);

  teamId = signal(0);

  team = signal<TeamDetailModel | null>(null);
  members = signal<TeamMember[]>([]);
  apiKeys = signal<TeamApiKey[]>([]);
  modelCount = signal(0);
  loading = signal(true);
  loadError = signal(false);

  activeTab = signal<Tab>('overview');

  editNameOpen = signal(false);
  editNameValue = signal('');
  editNameLoading = signal(false);
  editNameError = signal('');

  isLogosAdmin = computed(() => this.auth.currentUser()?.role === 'logos_admin');
  isCallerOwner = computed(() => !!this.team()?.is_caller_owner);
  canEdit = computed(() => this.isLogosAdmin() || this.isCallerOwner());

  visibleTabs = computed((): Tab[] => {
    const admin = this.isLogosAdmin();
    const owner = this.isCallerOwner();
    const tabs: Tab[] = ['overview', 'members'];
    if (admin || owner) tabs.push('application_keys');
    if (admin) tabs.push('providers');
    if (admin || owner) tabs.push('models', 'billing', 'settings');
    return tabs;
  });

  tabLabel: Record<Tab, string> = {
    overview: 'Overview',
    members: 'Members',
    application_keys: 'Application Keys',
    providers: 'Providers',
    models: 'Models',
    settings: 'Settings',
    billing: 'Billing',
  };

  ngOnInit(): void {
    const id = Number(this.route.snapshot.paramMap.get('id'));
    this.teamId.set(id);
    this.loadAll(id);
  }

  setTab(tab: Tab): void {
    this.activeTab.set(tab);
  }

  private async loadAll(teamId: number): Promise<void> {
    this.loading.set(true);
    this.loadError.set(false);

    try {
      const membersRes = await this.teamService.getTeamWithMembers(teamId);
      this.team.set(membersRes.team);
      this.members.set(membersRes.members);

      const isAdmin = this.isLogosAdmin();
      const isOwner = membersRes.team.is_caller_owner;
      if (isAdmin || isOwner) {
        const [apiKeys, models] = await Promise.all([
          this.teamService.getTeamApiKeys(teamId),
          this.teamService.getTeamModelPermissions(teamId),
        ]);
        this.apiKeys.set(apiKeys);
        this.modelCount.set(models.length);
      }
    } catch {
      this.loadError.set(true);
    } finally {
      this.loading.set(false);
    }
  }

  refresh(): void {
    this.loadAll(this.teamId());
  }

  openEditName(): void {
    this.editNameValue.set(this.team()?.name ?? '');
    this.editNameError.set('');
    this.editNameOpen.set(true);
  }

  closeEditName(): void {
    if (this.editNameLoading()) return;
    this.editNameOpen.set(false);
  }

  async submitEditName(): Promise<void> {
    const name = this.editNameValue().trim();
    if (!name || this.editNameLoading()) return;
    this.editNameLoading.set(true);
    this.editNameError.set('');
    try {
      const { name: newName } = await this.teamService.renameTeam(this.teamId(), name);
      this.team.update((t) => (t ? { ...t, name: newName } : t));
      this.editNameOpen.set(false);
    } catch {
      this.editNameError.set('Failed to rename team, please try again.');
    } finally {
      this.editNameLoading.set(false);
    }
  }

  onTeamDeleted(): void {
    this.router.navigate(['/team-management']);
  }
}
