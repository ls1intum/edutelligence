import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter } from '@angular/router';
import { describe, expect, it, vi } from 'vitest';
import { ThemeService } from '../../core/services/theme.service';
import { PublicStats as PublicStatsPage } from './public-stats';
import { PublicStats, PublicStatsService } from './public-stats.service';

function stats(overrides: Partial<PublicStats> = {}): PublicStats {
  return {
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
    ...overrides,
  };
}

describe('PublicStats page', () => {
  it('shows the platform totals from the public endpoint', async () => {
    const fixture = createPage(() => Promise.resolve(stats()));
    await fixture.whenStable();
    fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    const values = Array.from(root.querySelectorAll('.kpi-value')).map((el) => el.textContent!.trim());
    expect(values).toEqual(['5', '2', '5', '1.2']);
    // Every pie legend row carries its count, so no number rides on color alone.
    expect(root.querySelectorAll('.pie-legend .legend-item')).toHaveLength(2);
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
    expect(root.querySelectorAll('.pie-svg path')).toHaveLength(2);
    root.querySelector<HTMLInputElement>('.pie-legend input[type="checkbox"]')!.click();
    fixture.detectChanges();
    expect(root.querySelectorAll('.pie-svg path')).toHaveLength(1);
    // The hidden team keeps its dimmed legend row, still tickable back in.
    expect(root.querySelector('.pie-legend .legend-item.off')).not.toBeNull();
  });
});

function createPage(getStats: () => Promise<PublicStats>) {
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
