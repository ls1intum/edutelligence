import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it } from 'vitest';
import { PublicStatsSplit } from './public-stats.split';
import { ChartSlice } from './public-stats.utils';

const segments: ChartSlice[] = [
  { key: 'local', label: 'Local', value: 1, color: 'var(--series-1)', hidden: false },
  { key: 'cloud', label: 'Cloud', value: 3, color: 'var(--series-2)', hidden: false },
];

describe('PublicStatsSplit', () => {
  let fixture: ComponentFixture<PublicStatsSplit>;
  let root: HTMLElement;

  function render(segs: ChartSlice[] = segments, label = 'Requests by key type'): void {
    fixture = TestBed.createComponent(PublicStatsSplit);
    fixture.componentRef.setInput('segments', segs);
    fixture.componentRef.setInput('label', label);
    root = fixture.nativeElement as HTMLElement;
    fixture.detectChanges();
  }

  function segmentEls(): HTMLElement[] {
    return Array.from(root.querySelectorAll<HTMLElement>('.segment'));
  }

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [PublicStatsSplit] }).compileComponents();
  });

  it('sizes each segment by its share of the total', () => {
    render();
    const [local, cloud] = segmentEls();
    expect(local.style.flexGrow).toBe('1');
    expect(cloud.style.flexGrow).toBe('3');
  });

  it('keeps the label, count and percent on every legend row', () => {
    render();
    const rows = root.querySelectorAll<HTMLElement>('.legend-item');
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain('Local');
    expect(rows[0].textContent).toContain('1');
    expect(rows[0].textContent).toContain('25%');
    expect(rows[1].textContent).toContain('Cloud');
    expect(rows[1].textContent).toContain('75%');
  });

  it('omits zero segments from the bar but reports them in the legend', () => {
    render([
      { key: 'local', label: 'Local', value: 0, color: 'var(--series-1)', hidden: false },
      { key: 'cloud', label: 'Cloud', value: 4, color: 'var(--series-2)', hidden: false },
    ]);
    expect(segmentEls()).toHaveLength(1);
    const rows = root.querySelectorAll<HTMLElement>('.legend-item');
    expect(rows).toHaveLength(2);
  });

  it('shows the empty state when the total is zero', () => {
    render(segments.map((s) => ({ ...s, value: 0 })));
    expect(root.querySelector('.split-empty')!.textContent).toContain('No successful requests yet');
    expect(segmentEls()).toHaveLength(0);
  });

  it('names the bar for assistive technology via the label input', () => {
    render(segments, 'Local versus cloud requests');
    expect(root.querySelector('.split-bar')!.getAttribute('aria-label')).toBe(
      'Local versus cloud requests'
    );
  });
});
