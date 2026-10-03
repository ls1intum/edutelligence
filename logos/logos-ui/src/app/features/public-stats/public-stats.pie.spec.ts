import { Component, ComponentRef } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';
import { PublicStatsPie } from './public-stats.pie';
import { ChartSlice } from './public-stats.utils';

const slices: ChartSlice[] = [
  { key: 'a', label: 'Alpha', value: 3, color: 'var(--series-1)', hidden: false },
  { key: 'b', label: 'Beta', value: 1, color: 'var(--series-2)', hidden: false },
  { key: 'c', label: 'Gamma', value: 2, color: 'var(--series-3)', hidden: true },
];

function pie(): { fixture: ComponentRef<HostComponent>; host: HostComponent } {
  const fixture = TestBed.createComponent(HostComponent);
  fixture.detectChanges();
  return { fixture, host: fixture.componentInstance };
}

function paths(root: Element): Element[] {
  return Array.from(root.querySelectorAll('path'));
}

function legendItems(root: Element): Element[] {
  return Array.from(root.querySelectorAll<HTMLElement>('.legend-item'));
}

function checkboxes(root: Element): HTMLInputElement[] {
  return Array.from(root.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'));
}

describe('PublicStatsPie', () => {
  it('draws one wedge per visible slice only', () => {
    const { fixture, host } = pie();
    host.slice = [...slices];
    fixture.detectChanges();
    expect(paths(fixture.nativeElement)).toHaveLength(2); // Gamma is hidden
    const wedges = paths(fixture.nativeElement).map((p) => p.getAttribute('d'));
    expect(wedges.every((d) => d?.startsWith('M 100 100 L '))).toBe(true);
  });

  it('re-partitions the remaining slices when one is hidden', () => {
    const { fixture, host } = pie();
    host.slice = [...slices];
    fixture.detectChanges();
    // Alpha shows its share of the visible total (3 of 4).
    expect(fixture.nativeElement.querySelector('.legend-item .value')!.textContent).toContain('75%');
  });

  it('dims a hidden legend row but keeps it tickable', () => {
    const { fixture } = pie();
    const rows = legendItems(fixture.nativeElement);
    expect(rows).toHaveLength(3);
    expect(rows[2].classList.contains('off')).toBe(true);
    expect(checkboxes(fixture.nativeElement)[2].checked).toBe(false);
    // The swatch color is still shown: hiding is not erasing.
    expect(rows[2].querySelector('.swatch')).not.toBeNull();
  });

  it('emits the slice key when a legend checkbox is ticked', () => {
    const { fixture } = pie();
    checkboxes(fixture.nativeElement)[0].click();
    expect(fixture.componentInstance.toggled).toEqual(['a']);
  });

  it('shows the empty state when every slice is hidden or zero', () => {
    const { fixture, host } = pie();
    host.slice = [...slices, { key: 'z', label: 'Idle', value: 0, color: 'x', hidden: true }].map((s) => ({
      ...s,
      hidden: true,
    }));
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.pie-empty')!.textContent).toContain('No successful requests yet');
    expect(paths(fixture.nativeElement)).toHaveLength(0);
  });

  it('names the pie for assistive technology via the title input', () => {
    const { fixture, host } = pie();
    host.title = 'Requests per team';
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('svg')!.getAttribute('aria-label')).toBe('Requests per team');
  });
});

@Component({
  selector: 'public-stats-pie-host',
  standalone: true,
  imports: [PublicStatsPie],
  template: `<app-public-stats-pie
    [slices]="slice"
    [title]="title"
    (toggleSlice)="toggled.push($event)"
  />`,
})
class HostComponent {
  slice = [...slices];
  title = 'Requests per team';
  toggled: string[] = [];
}
