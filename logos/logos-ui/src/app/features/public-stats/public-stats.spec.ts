import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { describe, expect, it, vi } from 'vitest';
import { ThemeService } from '../../core/services/theme.service';
import { PublicStats as PublicStatsPage } from './public-stats';
import { PublicStats, PublicStatsDays, PublicStatsService } from './public-stats.service';
import { usageFields } from './public-stats.testing';

function stats(overrides: Partial<PublicStats> = {}): PublicStats {
  return {
    days: '30',
    students: 5,
    teams: 2,
    successful_requests: 5,
    average_requests_per_user: 1.2,
    requests_per_team: [
      { team_id: 1, team_name: 'Alpha', requests: 3 },
      { team_id: 2, team_name: 'Beta', requests: 2 },
    ],
    requests_by_key_type: { developer: 3, application: 2, service: 0 },
    local_cloud_requests: { local: 1, cloud: 4 },
    ...usageFields(),
    ...overrides,
  };
}

describe('PublicStats page', () => {
  it('shows the platform totals from the public endpoint', async () => {
    const fixture = createPage(() => Promise.resolve(stats()));
    await fixture.whenStable();
    fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    const values = Array.from(root.querySelectorAll('.kpi-grid .kpi-value')).map((el) => el.textContent!.trim());
    // Active people, regular users, published teams, requests, tokens, per-student average.
    expect(values).toEqual(['0', '0', '2', '5', '0', '1.2']);
    expect(root.textContent).toContain('last 30 days');
    // Every donut legend row carries its count, so no number rides on color alone.
    expect(root.querySelectorAll('.vram-donut__legend-item')).toHaveLength(2);
  });

  it('shows the growth chart, the usage table and the Logos Agent figures', async () => {
    const fixture = createPage(() =>
      Promise.resolve(
        stats({
          ...usageFields({
            active_persons: 7,
            monthly: [
              {
                month: '2026-08',
                teams: 2,
                persons: 4,
                students: 3,
                requests: 100,
                local_requests: 90,
                tokens: 1000,
                agent_sessions: 0,
                agent_users: 0,
              },
              {
                month: '2026-09',
                teams: 3,
                persons: 7,
                students: 5,
                requests: 300,
                local_requests: 250,
                tokens: 5000,
                agent_sessions: 12,
                agent_users: 3,
              },
            ],
            usage_per_person: {
              count: 7,
              suppressed: false,
              requests: { median: 646, p90: 82000 },
              tokens: { median: 3_700_000, p90: 4_300_000_000 },
              active_days: { median: 6.5, p90: 22 },
            },
            agent: { sessions: 12, users: 3, succeeded: 10, pull_requests: 4, first_session_day: '2026-09-03' },
          }),
        })
      )
    );
    await fixture.whenStable();
    fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;

    expect(root.querySelectorAll('.trend-bar')).toHaveLength(2);
    // The marker sits on the month of the first Logos Agent session.
    expect(root.querySelector('.trend-slot.marked .trend-marker-label')?.textContent?.trim()).toBe('Logos Agent');
    const firstRow = root.querySelector('.usage-table tbody tr')!;
    expect(firstRow.textContent).toContain('646');
    expect(root.querySelector('.table-note')).toBeNull();
    const agentValues = Array.from(root.querySelectorAll('.mini-kpi .kpi-value')).map((el) => el.textContent!.trim());
    expect(agentValues).toEqual(['12', '3', '10', '4']);
  });

  it('reloads when the time window changes', async () => {
    const getStats = vi.fn(async (days: PublicStatsDays = '30') => stats({ days }));
    const fixture = createPage(getStats);
    await fixture.whenStable();
    fixture.detectChanges();
    expect(getStats).toHaveBeenCalledWith('30');

    const root = fixture.nativeElement as HTMLElement;
    const sevenDay = Array.from(root.querySelectorAll<HTMLButtonElement>('.window-segment')).find(
      (btn) => btn.textContent?.trim() === '7 days'
    )!;
    sevenDay.click();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(getStats).toHaveBeenCalledWith('7');
    expect(root.textContent).toContain('last 7 days');
  });

  it('shows the loading state until the endpoint answers', () => {
    let resolveStats!: (value: PublicStats) => void;
    const fixture = createPage(
      () =>
        new Promise<PublicStats>((resolve) => {
          resolveStats = resolve;
        })
    );
    fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    expect(root.querySelector('.loading')!.textContent).toContain('Loading the platform numbers');
    // Unblock after the assertion so the settled promise cannot fail the run.
    resolveStats(stats());
  });

  it('reports a load failure instead of a blank page', async () => {
    const fixture = createPage(() => Promise.reject(new Error('boom')));
    // Rejected promises settle outside whenStable's happy path — flush the
    // catch that sets the error signal, then re-render.
    await Promise.resolve();
    await Promise.resolve();
    fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    expect(root.querySelector('[role="alert"]')!.textContent).toContain('could not be loaded');
  });

  it('hides a team from the pie when its legend box is unticked', async () => {
    const fixture = createPage(() => Promise.resolve(stats()));
    await fixture.whenStable();
    fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    expect(root.querySelectorAll('.vram-donut__svg path')).toHaveLength(2);
    root.querySelector<HTMLInputElement>('.vram-donut__legend input[type="checkbox"]')!.click();
    fixture.detectChanges();
    expect(root.querySelectorAll('.vram-donut__svg path')).toHaveLength(1);
    // The hidden team keeps its dimmed legend row, still tickable back in.
    expect(root.querySelectorAll('.vram-donut__legend-item')).toHaveLength(2);
    expect(root.querySelector('.vram-donut__legend-item--off')).not.toBeNull();
  });

  it('explains what a service key is next to the key-type split', async () => {
    const fixture = createPage(() => Promise.resolve(stats({ requests_by_key_type: { developer: 1, application: 1, service: 1 } })));
    await fixture.whenStable();
    fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    expect(root.textContent).toContain('Service keys');
    expect(root.textContent).toContain('Keys for automated backend jobs');
  });
});

function createPage(getStats: (days?: PublicStatsDays) => Promise<PublicStats>) {
  TestBed.configureTestingModule({
    imports: [HostComponent],
    providers: [
      provideRouter([]),
      { provide: PublicStatsService, useValue: { getStats } },
      // The header's theme toggle reads localStorage/matchMedia; stub the
      // preference so the page can render under jsdom without a storage polyfill.
      { provide: ThemeService, useValue: { isDark: signal(false), toggle: vi.fn() } },
    ],
  });
  const fixture = TestBed.createComponent(HostComponent);
  fixture.detectChanges();
  return fixture;
}

@Component({
  selector: 'public-stats-page-host',
  standalone: true,
  imports: [PublicStatsPage],
  template: `<app-public-stats />`,
})
class HostComponent {}
