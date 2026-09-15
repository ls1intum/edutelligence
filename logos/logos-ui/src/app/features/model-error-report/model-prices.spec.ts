import { ModelPriceEntry, ModelProviderPrices } from '../../shared/models/model-price.model';
import {
  formatPricePerUnit,
  groupPriceRows,
  priceProviderCards,
  priceUnitLabel,
  quantityLabel,
  variantLabel,
} from './model-prices';

const makePrice = (overrides: Partial<ModelPriceEntry> = {}): ModelPriceEntry => ({
  quantity: 'billed_input_uncached',
  unit: 'token',
  min_context_tokens: 0,
  service_tier: 'default',
  price_per_k_unit: 250_000,
  valid_from: '2025-08-01T00:00:00Z',
  ...overrides,
});

describe('quantityLabel', () => {
  it('uses provider-style names for known billable quantities', () => {
    expect(quantityLabel('billed_input_uncached')).toBe('Input');
    expect(quantityLabel('billed_input_cache_read')).toBe('Cached input');
    expect(quantityLabel('billed_output_reasoning')).toBe('Reasoning');
  });

  it('humanizes unknown quantities instead of hiding them', () => {
    expect(quantityLabel('billed_something_new')).toBe('Something New');
  });
});

describe('priceUnitLabel', () => {
  it('quotes countable units per 1M and durations per second', () => {
    expect(priceUnitLabel('token')).toBe('1M tokens');
    expect(priceUnitLabel('character')).toBe('1M characters');
    expect(priceUnitLabel('millisecond')).toBe('second');
    expect(priceUnitLabel('request')).toBe('request');
  });

  it('passes through units without a known label', () => {
    expect(priceUnitLabel('furlong')).toBe('furlong');
  });
});

describe('formatPricePerUnit', () => {
  it('converts micro-cents per 1k tokens to dollars per 1M tokens', () => {
    // gpt-4o list price: 2.5e-6 USD/token stored as 250000 micro-cents/1k.
    expect(formatPricePerUnit(250_000, 'token')).toBe('$2.50 / 1M tokens');
  });

  it('converts micro-cents per 1k milliseconds to dollars per second', () => {
    // $0.016 per second stored as 1.6e6 micro-cents/1k-ms.
    expect(formatPricePerUnit(1_600_000, 'millisecond')).toBe('$0.016 / second');
  });

  it('converts micro-cents per 1k items to dollars per single item', () => {
    // $0.01 per request stored as 1e9 micro-cents/1k requests.
    expect(formatPricePerUnit(1_000_000_000, 'request')).toBe('$0.01 / request');
  });

  it('keeps small rates legible instead of collapsing to $0.00', () => {
    expect(formatPricePerUnit(10_000, 'token')).toBe('$0.10 / 1M tokens');
  });
});

describe('variantLabel', () => {
  it('is null for the base rate', () => {
    expect(variantLabel(0, 'default')).toBeNull();
  });

  it('labels context tiers and service tiers separately', () => {
    expect(variantLabel(272_000, 'default')).toBe('context ≥ 272k tokens');
    expect(variantLabel(0, 'batch')).toBe('batch');
    expect(variantLabel(272_000, 'batch')).toBe('batch, context ≥ 272k tokens');
  });
});

describe('groupPriceRows', () => {
  it('groups rows per quantity and orders input before output', () => {
    const dimensions = groupPriceRows([
      makePrice({ quantity: 'billed_output_text', price_per_k_unit: 1_000_000 }),
      makePrice({ quantity: 'billed_input_uncached' }),
    ]);

    expect(dimensions.map((d) => d.quantity)).toEqual([
      'billed_input_uncached',
      'billed_output_text',
    ]);
    expect(dimensions[0]!.label).toBe('Input');
    expect(dimensions[1]!.unitLabel).toBe('1M tokens');
  });

  it('keeps history newest-first and marks only the newest rate current', () => {
    const dimensions = groupPriceRows([
      makePrice({ valid_from: '2025-08-01T00:00:00Z', price_per_k_unit: 250_000 }),
      makePrice({ valid_from: '2026-01-15T00:00:00Z', price_per_k_unit: 300_000 }),
    ]);

    const rows = dimensions[0]!.rows;
    expect(rows).toHaveLength(2);
    expect(rows[0]!.validFrom).toBe('2026-01-15T00:00:00Z');
    expect(rows[0]!.priceText).toBe('$3.00 / 1M tokens');
    expect(rows[0]!.isCurrent).toBe(true);
    expect(rows[1]!.validFrom).toBe('2025-08-01T00:00:00Z');
    expect(rows[1]!.isCurrent).toBe(false);
  });

  it('treats context tiers and service tiers as separate current rates', () => {
    const dimensions = groupPriceRows([
      makePrice({ min_context_tokens: 272_000, price_per_k_unit: 600_000 }),
      makePrice({ service_tier: 'batch', price_per_k_unit: 125_000 }),
      makePrice({ price_per_k_unit: 250_000 }),
    ]);

    const rows = dimensions[0]!.rows;
    // Tiers sort below the base rate; each tier's newest row is current.
    expect(rows.map((row) => row.variantLabel)).toEqual([null, 'batch', 'context ≥ 272k tokens']);
    expect(rows.every((row) => row.isCurrent)).toBe(true);
  });

  it('renders pre-formatted price and date text for the template', () => {
    const dimensions = groupPriceRows([makePrice()]);
    const row = dimensions[0]!.rows[0]!;

    expect(row.priceText).toBe('$2.50 / 1M tokens');
    expect(row.sinceText).toMatch(/^\d{2}\.\d{2}\.\d{4}$/);
  });
});

const makeProvider = (overrides: Partial<ModelProviderPrices> = {}): ModelProviderPrices => ({
  provider_id: 1,
  provider_name: 'OpenAI Production',
  provider_type: 'cloud',
  cloud_provider_type: 'openai',
  prices: [makePrice()],
  ...overrides,
});

describe('priceProviderCards', () => {
  it('keeps only cloud providers and groups their price rows', () => {
    const cards = priceProviderCards([
      makeProvider({
        provider_id: 2,
        provider_name: 'Local Worker',
        provider_type: 'logosnode',
        cloud_provider_type: null,
      }),
      makeProvider(),
    ]);

    expect(cards).toHaveLength(1);
    expect(cards[0]!.provider.provider_id).toBe(1);
    expect(cards[0]!.dimensions.map((d) => d.quantity)).toEqual(['billed_input_uncached']);
    expect(cards[0]!.dimensions[0]!.rows[0]!.priceText).toBe('$2.50 / 1M tokens');
  });

  it('is empty when the model has no cloud providers', () => {
    expect(
      priceProviderCards([makeProvider({ provider_type: 'logosnode', cloud_provider_type: null })]),
    ).toEqual([]);
  });
});
