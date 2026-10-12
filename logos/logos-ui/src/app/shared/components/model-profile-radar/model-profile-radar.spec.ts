import { describe, expect, it } from 'vitest';
import { ModelProfileRadarComponent } from './model-profile-radar';

describe('ModelProfileRadarComponent labels', () => {
  const labels = () => {
    const component = new ModelProfileRadarComponent();
    component.size = 96;
    return Object.fromEntries(component.view().labels.map((l) => [l.key, l]));
  };

  it('lets side labels grow away from the chart instead of across it', () => {
    const { latency, quality, price } = labels();
    // Latency is the top spoke, Quality bottom right, Price bottom left.
    expect(latency.anchor).toBe('middle');
    expect(quality.anchor).toBe('start');
    expect(price.anchor).toBe('end');
    expect(quality.x).toBeGreaterThan(48);
    expect(price.x).toBeLessThan(48);
  });
});
