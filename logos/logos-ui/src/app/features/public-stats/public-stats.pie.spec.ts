import { Component } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';
import { PublicStatsPie } from './public-stats.pie';
import { ChartSlice } from './public-stats.utils';

const slices: ChartSlice[] = [
  { key: 'a', label: 'Alpha', value: 3, color: 'var(--series-1)', hidden: false },
  { key: 'b', label: 'Beta', value: 1, color: 'var(--series-2)', hidden: false },
  { key: 'c', label: 'Gamma', value: 2, color: 'var(--series-3)', hidden: true },
];

function pie(): { fixture: ComponentFixture<HostComponent>; host: HostComponent } {
  const fixture = TestBed.createComponent(HostComponent);
  fixture.detectChanges();
  return { fixture, host: fixture.componentInstance };
}

function rootOf(fixture: ComponentFixture<HostComponent>): HTMLElement {
  return fixture.nativeElement as HTMLElement;
}

function paths(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll('path'));
}

function legendItems(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>('.legend-item'));
}

function checkboxes(root: HTMLElement): HTMLInputElement[] {
  return Array.from(root.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'));
}

describe('PublicStatsPie', () => {
  it('draws one wedge per visible slice only', () => {
    const { fixture, host } = pie();
    host.slice = [...slices];
    fixture.detectChanges();
    const root = rootOf(fixture);
    expect(paths(root)).toHaveLength(2); // Gamma is hidden
    const wedges = paths(root).map((p) => p.getAttribute('d'));
    expect(wedges.every((d) => d?.startsWith('M 100 100 L '))).toBe(true);
  });

  it('re-partitions the remaining slices when one is hidden', () => {
    const { fixture, host } = pie();
    host.slice = [...slices];
    fixture.detectChanges();
    // Alpha shows its share of the visible total (3 of 4).
    expect(rootOf(fixture).querySelector('.legend-item .value')!.textContent).toContain('75%');
  });

  it('dims a hidden legend row but keeps it tickable', () => {
    const { fixture } = pie();
    const rows = legendItems(rootOf(fixture));
    expect(rows).toHaveLength(3);
    expect(rows[2].classList.contains('off')).toBe(true);
    expect(checkboxes(rootOf(fixture))[2].checked).toBe(false);
    // The swatch color is still shown: hiding is not erasing.
    expect(rows[2].querySelector('.swatch')).not.toBeNull();
  });

  it('emits the slice key when a legend checkbox is ticked', () => {
    const { fixture } = pie();
    checkboxes(rootOf(fixture))[0].click();
    expect(fixture.componentInstance.toggled).toEqual(['a']);
  });

  it('keeps the legend when every slice is hidden so teams can be restored', () => {
    const { fixture, host } = pie();
    host.slice = slices.map((s) => ({ ...s, hidden: true }));
    fixture.detectChanges();
    const root = rootOf(fixture);
    expect(root.querySelector('.pie-empty')!.textContent).toContain('All teams are hidden');
    expect(paths(root)).toHaveLength(0);
    expect(legendItems(root)).toHaveLength(3);
    expect(checkboxes(root)).toHaveLength(3);
  });

  it('shows the no-data state when every slice is zero', () => {
    const { fixture, host } = pie();
    host.slice = slices.map((s) => ({ ...s, value: 0, hidden: false }));
    fixture.detectChanges();
    const root = rootOf(fixture);
    expect(root.querySelector('.pie-empty')!.textContent).toContain('No successful requests yet');
    expect(legendItems(root)).toHaveLength(0);
  });

  it('names the pie for assistive technology via the title input', () => {
    const { fixture, host } = pie();
    host.title = 'Requests per team';
    fixture.detectChanges();
    expect(rootOf(fixture).querySelector('svg')!.getAttribute('aria-label')).toBe('Requests per team');
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
