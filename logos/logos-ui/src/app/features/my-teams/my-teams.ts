import { Component, inject, OnInit, signal, ChangeDetectionStrategy } from '@angular/core';
import { TeamManagementService } from '../../core/services/team-management.service';
import { MyTeam } from '../../shared/models/team.model';
import { ErrorMessageComponent } from '../../shared/components/error-message/error-message';
import { IconTileComponent } from '../../shared/components/icon-tile/icon-tile';

@Component({
  selector: 'app-my-teams',
  standalone: true,
  imports: [ErrorMessageComponent, IconTileComponent],
  templateUrl: './my-teams.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './my-teams.scss',
})
export class MyTeams implements OnInit {
  private teamService = inject(TeamManagementService);

  teams = signal<MyTeam[]>([]);
  loading = signal(true);
  loadError = signal(false);

  async ngOnInit(): Promise<void> {
    try {
      const teams = await this.teamService.getMyTeams();
      this.teams.set(teams);
    } catch {
      this.loadError.set(true);
    } finally {
      this.loading.set(false);
    }
  }

  ownerLabel(team: MyTeam): string {
    if (!team.owners?.length) return '—';
    const o = team.owners[0];
    return `${o.prename ?? ''} ${o.name ?? ''}`.trim() || '—';
  }

  formatDollars(microCents: number): string {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(
      microCents / 100_000_000,
    );
  }

  budgetPct(team: MyTeam): number {
    if (!team.team_monthly_budget_micro_cents) return 0;
    return Math.min(
      100,
      (team.budget_used_micro_cents / team.team_monthly_budget_micro_cents) * 100,
    );
  }
}
