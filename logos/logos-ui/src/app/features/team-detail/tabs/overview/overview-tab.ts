import { Component, Input, ChangeDetectionStrategy } from '@angular/core';
import { TeamDetail, TeamMember, TeamApiKey } from '../../../../shared/models/team.model';

const MICRO = 100_000_000;

@Component({
  selector: 'app-overview-tab',
  standalone: true,
  imports: [],
  templateUrl: './overview-tab.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './overview-tab.scss',
})
export class OverviewTabComponent {
  @Input() team!: TeamDetail;
  @Input() members: TeamMember[] = [];
  @Input() apiKeys: TeamApiKey[] = [];
  @Input() modelCount = 0;

  get ownerCount(): number {
    return this.members.filter((m) => m.is_owner).length;
  }

  get memberCount(): number {
    return this.members.filter((m) => !m.is_owner).length;
  }

  get budgetPct(): number {
    const limit = this.team.team_monthly_budget_micro_cents;
    const used = this.team.budget_used_micro_cents ?? 0;
    if (!limit) return 0;
    return Math.min((used / limit) * 100, 100);
  }

  get budgetBarColor(): string {
    return this.budgetPct >= 90 ? '#ef4444' : 'rgb(var(--color-primary-500))';
  }

  formatDollars(mc: number | null): string {
    if (mc === null || mc === undefined) return '-';
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(
      mc / MICRO,
    );
  }

  formatRate(v: number | null): string {
    if (v === null || v === undefined) return '∞';
    if (v >= 1000) return `${(v / 1000).toFixed(0)}k`;
    return `${v}`;
  }
}
