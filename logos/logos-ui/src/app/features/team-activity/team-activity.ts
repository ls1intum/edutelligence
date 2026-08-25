import {
  ChangeDetectionStrategy,
  Component,
  OnDestroy,
  OnInit,
  computed,
  inject,
  signal,
} from '@angular/core';
import { CommonModule } from '@angular/common';

import { AppSelectOption, SelectComponent } from '../../shared/components/select/select';
import { TeamManagementService } from '../../core/services/team-management.service';
import { Team } from '../../shared/models/team.model';
import { TeamActivityService } from './team-activity.service';
import { TeamActivityPayload } from './team-activity.models';

/** How often the live counts are refreshed while the page is open. */
const REFRESH_MS = 5_000;

/** Windows offered for the usage figures. */
const DAY_OPTIONS: AppSelectOption[] = [
  { value: '1', label: 'Last 24 hours' },
  { value: '7', label: 'Last 7 days' },
  { value: '30', label: 'Last 30 days' },
  { value: '90', label: 'Last 90 days' },
];

/**
 * One team's activity, for the people who run a team rather than the cluster
 * (issue #776).
 *
 * Two questions and no more: what is running right now, and what has the team
 * spent. The statistics page answers a great deal else — VRAM curves, lane
 * health, per-worker GPUs — and none of that is actionable for someone whose
 * concern is their own team's usage.
 */
@Component({
  selector: 'app-team-activity',
  standalone: true,
  imports: [CommonModule, SelectComponent],
  templateUrl: './team-activity.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './team-activity.scss',
})
export class TeamActivity implements OnInit, OnDestroy {
  private teamManagement = inject(TeamManagementService);
  private activityService = inject(TeamActivityService);

  readonly teams = signal<Team[]>([]);
  readonly selectedTeamId = signal<number | null>(null);
  readonly days = signal(7);

  readonly activity = signal<TeamActivityPayload | null>(null);
  readonly loading = signal(true);
  readonly error = signal<string | null>(null);

  readonly dayOptions = DAY_OPTIONS;
  private timer: ReturnType<typeof setInterval> | null = null;

  /**
   * Teams this page can actually answer for.
   *
   * The endpoint requires ownership, and the team list a non-owner sees
   * includes teams they are merely a member of. Offering those would put
   * entries in the picker that reply 403 — a filter here rather than an error
   * message there.
   */
  readonly teamOptions = computed<AppSelectOption[]>(() =>
    this.teams()
      .filter((t) => t.is_caller_owner)
      .map((t) => ({ value: String(t.id), label: t.name })),
  );

  readonly selectedDaysValue = computed(() => String(this.days()));

  readonly selectedTeamValue = computed(() => {
    const id = this.selectedTeamId();
    return id === null ? '' : String(id);
  });

  readonly selectedTeamName = computed(
    () => this.teams().find((t) => t.id === this.selectedTeamId())?.name ?? '',
  );

  readonly hasNoTeams = computed(() => !this.loading() && this.teamOptions().length === 0);

  /** In flight right now — the number the live view exists for. */
  readonly inFlight = computed(() => {
    const live = this.activity()?.live;
    return live ? live.queued + live.running : 0;
  });

  readonly failureRate = computed(() => {
    const live = this.activity()?.live;
    if (!live || live.finished === 0) return null;
    return (live.failed / live.finished) * 100;
  });

  ngOnInit(): void {
    void this.loadTeams();
    // The live counts are the point, so they refresh on their own. The usage
    // figures come along for the ride: one query answers both, and a team's
    // spend over days does not move fast enough to need its own cadence.
    this.timer = setInterval(() => void this.loadActivity(), REFRESH_MS);
  }

  ngOnDestroy(): void {
    if (this.timer !== null) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  setTeam(value: string | null): void {
    const id = value ? Number(value) : null;
    if (!Number.isFinite(id as number)) return;
    this.selectedTeamId.set(id);
    this.activity.set(null);
    void this.loadActivity();
  }

  setDays(value: string | null): void {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed <= 0) return;
    this.days.set(parsed);
    void this.loadActivity();
  }

  formatNumber(value: number | null | undefined): string {
    return typeof value === 'number' ? value.toLocaleString() : '—';
  }

  /** Token totals run to nine figures; the exact digit is never the question. */
  formatTokens(value: number | null | undefined): string {
    if (typeof value !== 'number' || value <= 0) return '0';
    if (value >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(1)}B`;
    if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
    if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
    return String(value);
  }

  keyLabel(keyName: string, environment: string | null): string {
    // "-" is the placeholder a key with no environment carries in the database.
    return environment && environment !== '-' ? `${keyName} · ${environment}` : keyName;
  }

  private async loadTeams(): Promise<void> {
    this.loading.set(true);
    try {
      const teams = await this.teamManagement.getTeams();
      this.teams.set(teams);
      const first = this.teamOptions()[0];
      if (first) {
        this.selectedTeamId.set(Number(first.value));
        await this.loadActivity();
      }
    } catch {
      this.error.set('Could not load your teams.');
    } finally {
      this.loading.set(false);
    }
  }

  private async loadActivity(): Promise<void> {
    const teamId = this.selectedTeamId();
    if (teamId === null) return;
    try {
      this.activity.set(await this.activityService.getActivity(teamId, this.days()));
      this.error.set(null);
    } catch {
      // Keep whatever is on screen: this runs on a timer, and blanking the page
      // over one failed poll would make a brief network blip look like an
      // outage. The figures are labelled by the window they were taken for.
      this.error.set('Could not refresh activity.');
    }
  }
}
