import { Component, inject, OnInit, signal } from '@angular/core';
import { TeamManagementService } from '../../core/services/team-management.service';
import { MyTeam } from '../../shared/models/team.model';
import { ErrorMessageComponent } from '../../shared/components/error-message/error-message';

@Component({
  selector: 'app-my-teams',
  standalone: true,
  imports: [ErrorMessageComponent],
  templateUrl: './my-teams.html',
  styleUrl: './my-teams.scss',
})
export class MyTeams implements OnInit {
  private teamService = inject(TeamManagementService);

  teams     = signal<MyTeam[]>([]);
  loading   = signal(true);
  loadError = signal(false);

  private readonly avatarColors = [
    '139 92 246',
    '56 189 248',
    '34 197 94',
    '234 179 8',
    '239 68 68',
    '167 139 250',
  ];

  ngOnInit(): void {
    this.teamService.getMyTeams().subscribe({
      next: teams => { this.teams.set(teams); this.loading.set(false); },
      error: ()    => { this.loadError.set(true); this.loading.set(false); },
    });
  }

  avatarColorBg(team: MyTeam): string {
    const ch = this.avatarColors[team.id % this.avatarColors.length];
    const [r, g, b] = ch.split(' ');
    return `rgba(${r},${g},${b},0.15)`;
  }

  avatarColorText(team: MyTeam): string {
    const ch = this.avatarColors[team.id % this.avatarColors.length];
    const [r, g, b] = ch.split(' ');
    return `rgba(${r},${g},${b},1)`;
  }

  ownerLabel(team: MyTeam): string {
    if (!team.owners?.length) return '—';
    const o = team.owners[0];
    return `${o.prename ?? ''} ${o.name ?? ''}`.trim() || '—';
  }

  formatDollars(microCents: number): string {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' })
      .format(microCents / 100_000_000);
  }

  budgetPct(team: MyTeam): number {
    if (!team.team_monthly_budget_micro_cents) return 0;
    return Math.min(100, (team.budget_used_micro_cents / team.team_monthly_budget_micro_cents) * 100);
  }
}
