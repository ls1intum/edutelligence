import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';
import { PublicStatsPie } from './public-stats.pie';
import { ChartSlice } from './public-stats.utils';

const slices: ChartSlice[] = [
  { key: 'a', label: 'Alpha', value: 3, color: 'var(--series-1)', hidden: false },
  { key: 'b', label: 'Beta', value: 1, color: 'var(--series-2)', hidden: false },
  { key: 'c', label: 'Gamma', value: 2, color: 'var(--series-3)', hidden: true },
];

describe('PublicStatsPie', () => {
  let fixture: ComponentFixture<PublicStatsPie>;
  let root: HTMLElement;

  function render(slice: ChartSlice[] = slices, title = 'Requests per team'): void {
    fixture = TestBed.createComponent(PublicStatsPie);
    fixture.componentRef.setInput('slices', slice);
    fixture.componentRef.setInput('title', title);
    root = fixture.nativeElement as HTMLElement;
    fixture.detectChanges();
  }

  function paths(): SVGPathElement[] {
    return Array.from(root.querySelectorAll('path'));
  }

  function legendItems(): HTMLElement[] {
    return Array.from(root.querySelectorAll<HTMLElement>('.legend-item'));
  }

  function checkboxes(): HTMLInputElement[] {
    return Array.from(root.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'));
  }

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [PublicStatsPie] }).compileComponents();
  });

  it('draws one wedge per visible slice only', () => {
    render();
    expect(paths()).toHaveLength(2); // Gamma is hidden
    const wedges = paths().map((p) => p.getAttribute('d'));
    expect(wedges.every((d) => d?.startsWith('M 100 100 L '))).toBe(true);
  });

  it('re-partitions the remaining slices when one is hidden', () => {
    render();
    // Alpha shows its share of the visible total (3 of 4).
    expect(root.querySelector('.legend-item .value')!.textContent).toContain('75%');
  });

  it('dims a hidden legend row but keeps it tickable', () => {
    render();
    const rows = legendItems();
    expect(rows).toHaveLength(3);
    expect(rows[2].classList.contains('off')).toBe(true);
    expect(checkboxes()[2].checked).toBe(false);
    // The swatch color is still shown: hiding is not erasing.
    expect(rows[2].querySelector('.swatch')).not.toBeNull();
  });

  it('emits the slice key when a legend checkbox is ticked', () => {
    render();
    const toggled: string[] = [];
    fixture.componentInstance.toggleSlice.subscribe((key) => toggled.push(key));
    checkboxes()[0].click();
    expect(toggled).toEqual(['a']);
  });

  it('keeps the legend when every slice is hidden so teams can be restored', () => {
    render(slices.map((s) => ({ ...s, hidden: true })));
    expect(root.querySelector('.pie-empty')!.textContent).toContain('All teams are hidden');
    expect(paths()).toHaveLength(0);
    expect(legendItems()).toHaveLength(3);
    expect(checkboxes()).toHaveLength(3);
  });

  it('shows the no-data state when every slice is zero', () => {
    render(slices.map((s) => ({ ...s, value: 0, hidden: false })));
    expect(root.querySelector('.pie-empty')!.textContent).toContain('No successful requests yet');
    expect(legendItems()).toHaveLength(0);
  });

  it('names the pie for assistive technology via the title input', () => {
    render(slices, 'Requests per team');
    expect(root.querySelector('svg')!.getAttribute('aria-label')).toBe('Requests per team');
  });
});
