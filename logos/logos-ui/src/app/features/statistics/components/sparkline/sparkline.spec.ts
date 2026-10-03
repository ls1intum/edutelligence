import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { TestBed } from '@angular/core/testing';
import { SparklineComponent } from './sparkline';

const sparklineStyles = readStyleSheet('sparkline.scss');

/**
 * The polyline the sparkline draws.
 *
 * The line always spans the full width of the drawing, and the largest value
 * maps to the top edge, so a rising series reads as rising regardless of the
 * magnitude of the values.
 */
describe('points', () => {
  it('spans the full width and puts the maximum at the top', () => {
    const c = new SparklineComponent();
    c.data = [0, 1, 0];
    expect(c.points).toBe('0.00,27.00 46.00,1.00 92.00,27.00');
  });

  it('keeps proportions for values below the maximum', () => {
    const c = new SparklineComponent();
    c.data = [2, 4];
    expect(c.points).toBe('0.00,14.00 92.00,1.00');
  });

  it('centers a single point', () => {
    const c = new SparklineComponent();
    c.data = [5];
    expect(c.points).toBe('46.00,1.00');
  });

  it('draws nothing without data or with a flat zero series', () => {
    const c = new SparklineComponent();
    c.data = [];
    expect(c.points).toBe('');
    c.data = [0, 0];
    expect(c.points).toBe('');
  });
});

describe('shouldRender', () => {
  it('is true only for a series with at least one positive value', () => {
    const c = new SparklineComponent();
    c.data = [];
    expect(c.shouldRender).toBe(false);
    c.data = [0, 0];
    expect(c.shouldRender).toBe(false);
    c.data = [0, 3];
    expect(c.shouldRender).toBe(true);
  });
});

describe('rendered svg', () => {
  it('draws into the viewBox and carries no fixed size attributes', async () => {
    await TestBed.configureTestingModule({
      imports: [SparklineComponent],
    }).compileComponents();
    const fixture = TestBed.createComponent(SparklineComponent);
    fixture.componentInstance.data = [0, 1, 0];
    fixture.detectChanges();

    const svg = fixture.nativeElement.querySelector('svg.sparkline-svg');
    expect(svg).toBeInstanceOf(SVGElement);
    // The size comes from the stylesheet (which scales the line to the KPI
    // card slot), never from fixed attributes on the element — a fixed
    // 92x28 box is what used to push the line into the card border.
    expect(svg?.getAttribute('width')).toBeNull();
    expect(svg?.getAttribute('height')).toBeNull();
    expect(svg?.getAttribute('viewBox')).toBe('0 0 92 28');
  });

  it('renders nothing while there is no series to draw', async () => {
    await TestBed.configureTestingModule({
      imports: [SparklineComponent],
    }).compileComponents();
    const fixture = TestBed.createComponent(SparklineComponent);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('svg.sparkline-svg')).toBeNull();
  });
});

/**
 * The sizing contract of the stylesheet.
 *
 * The unit-test environment applies no layout, so the declarations that keep
 * the line inside the KPI card are pinned here as text: the host may shrink
 * below its natural width, and the drawing fills the host it is given
 * instead of keeping a fixed 92x28 box.
 */
describe('sparkline stylesheet', () => {
  it('lets the host shrink below its natural width', () => {
    expect(ruleBody(sparklineStyles, ':host')).toMatch(/min-width:\s*0/);
  });

  it('scales the drawing to the host instead of keeping a fixed box', () => {
    const body = ruleBody(sparklineStyles, '.sparkline-svg');
    expect(body).toMatch(/width:\s*100%/);
    expect(body).toMatch(/max-width:\s*92px/);
    // The lookbehind keeps this from matching the max-width cap.
    expect(body).not.toMatch(/(?<!-)width:\s*92px/);
    expect(body).not.toMatch(/height:\s*28px/);
  });
});

/**
 * Reads a stylesheet from the spec's directory as raw text. The unit-test
 * builder's pipeline cannot resolve `?raw` imports, and the environment
 * applies no layout — the specs pin CSS declarations as text instead.
 */
function readStyleSheet(file: string): string {
  return readFileSync(join(dirname(fileURLToPath(import.meta.url)), file), 'utf8');
}

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
