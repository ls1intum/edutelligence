import { Component, ComponentRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';
import { PublicStatsSplit } from './public-stats.split';
import { ChartSlice } from './public-stats.utils';

const segments: ChartSlice[] = [
  { key: 'local', label: 'Local', value: 1, color: 'var(--series-1)', hidden: false },
  { key: 'cloud', label: 'Cloud', value: 3, color: 'var(--series-2)', hidden: false },
];

function split(): { fixture: ComponentRef<HostComponent>; host: HostComponent } {
  const fixture = TestBed.createComponent(HostComponent);
  fixture.detectChanges();
  return { fixture, host: fixture.componentInstance };
}

function segments_(root: Element): Element[] {
  return Array.from(root.querySelectorAll('.segment'));
}

describe('PublicStatsSplit', () => {
  it('sizes each segment by its share of the total', () => {
    const { fixture } = split();
    const [local, cloud] = segments_(fixture.nativeElement);
    expect(local.style.flexGrow).toBe('1');
    expect(cloud.style.flexGrow).toBe('3');
  });

  it('keeps the label, count and percent on every legend row', () => {
    const { fixture } = split();
    const rows = fixture.nativeElement.querySelectorAll<HTMLElement>('.legend-item');
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain('Local');
    expect(rows[0].textContent).toContain('1');
    expect(rows[0].textContent).toContain('25%');
    expect(rows[1].textContent).toContain('Cloud');
    expect(rows[1].textContent).toContain('75%');
  });

  it('omits zero segments from the bar but reports them in the legend', () => {
    const { fixture, host } = split();
    host.segments = [
      { key: 'local', label: 'Local', value: 0, color: 'var(--series-1)', hidden: false },
      { key: 'cloud', label: 'Cloud', value: 4, color: 'var(--series-2)', hidden: false },
    ];
    fixture.detectChanges();
    expect(segments_(fixture.nativeElement)).toHaveLength(1);
    const rows = fixture.nativeElement.querySelectorAll<HTMLElement>('.legend-item');
    expect(rows).toHaveLength(2);
  });

  it('shows the empty state when the total is zero', () => {
    const { fixture, host } = split();
    host.segments = segments.map((s) => ({ ...s, value: 0 }));
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.split-empty')!.textContent).toContain('No successful requests yet');
    expect(segments_(fixture.nativeElement)).toHaveLength(0);
  });

  it('names the bar for assistive technology via the label input', () => {
    const { fixture, host } = split();
    host.label = 'Local versus cloud requests';
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.split-bar')!.getAttribute('aria-label')).toBe(
      'Local versus cloud requests'
    );
  });
});

@Component({
  selector: 'public-stats-split-host',
  standalone: true,
  imports: [PublicStatsSplit],
  template: `<app-public-stats-split [segments]="segments" [label]="label" />`,
})
class HostComponent {
  segments = [...segments];
  label = 'Requests by key type';
}
