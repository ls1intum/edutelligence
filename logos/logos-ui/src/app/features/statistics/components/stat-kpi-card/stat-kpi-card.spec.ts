import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import kpiCardStyles from './stat-kpi-card.scss?raw';
import statisticsStyles from '../../statistics.scss?raw';
import { StatKpiCardComponent } from './stat-kpi-card';
import { SparklineComponent } from '../sparkline/sparkline';

/**
 * The card as the statistics page uses it: a value, the projected right
 * slot, and the projected hint.
 */
@Component({
  standalone: true,
  imports: [StatKpiCardComponent, SparklineComponent],
  template: `
    <app-stats-kpi-card label="Requests" accent="#7C3AED" value="222,987">
      <app-stats-sparkline kpiRight [data]="spark" [color]="'#7C3AED'" />
      <span kpiHint>avg run 61.10s · queue 0.85s</span>
    </app-stats-kpi-card>
  `,
})
class KpiCardHost {
  spark = [0, 1, 0];
}

describe('slot placement', () => {
  it('keeps the right slot in the value row and the hint in its own', async () => {
    await TestBed.configureTestingModule({
      imports: [KpiCardHost],
    }).compileComponents();
    const fixture = TestBed.createComponent(KpiCardHost);
    fixture.detectChanges();

    // The slot rule below targets [kpiRight] inside .kpi-row-2 — the pin is
    // only meaningful while the projection really lands there.
    const row2 = fixture.nativeElement.querySelector('.kpi-row-2');
    expect(row2?.querySelector('[kpiRight] svg.sparkline-svg')).not.toBeNull();
    expect(row2?.querySelector('.kpi-value')).not.toBeNull();
    const row3 = fixture.nativeElement.querySelector('.kpi-row-3');
    expect(row3?.querySelector('[kpiHint]')).not.toBeNull();
  });
});

/**
 * The sizing contract of the stylesheets.
 *
 * The unit-test environment applies no layout, so the declarations that keep
 * a card's right slot inside the card's padding are pinned here as text: the
 * slot may shrink below whatever it draws, and the lane bars — the one slot
 * that cannot scale — clip at the padding instead of reaching the border.
 */
describe('right-slot sizing contract', () => {
  it('lets the projected right slot shrink to the space the card offers', () => {
    expect(ruleBody(kpiCardStyles, '.kpi-row-2 ::ng-deep [kpiRight]')).toMatch(
      /min-width:\s*0/,
    );
  });

  it('clips the lane micro-bars at the card padding', () => {
    expect(ruleBody(statisticsStyles, '.stats-lane-bars')).toMatch(/overflow:\s*hidden/);
  });
});

/**
 * The declaration block of a top-level rule, so the assertions above read
 * against the stylesheet the same way a browser would apply it.
 */
function ruleBody(source: string, selector: string): string {
  const start = source.indexOf(selector);
  expect(start).toBeGreaterThanOrEqual(0);
  const open = source.indexOf('{', start);
  expect(open).toBeGreaterThan(start);
  const close = source.indexOf('}', open);
  expect(close).toBeGreaterThan(open);
  return source.slice(open + 1, close);
}
