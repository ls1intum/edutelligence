import { ModelPriceEntry, ModelProviderPrices } from '../../shared/models/model-price.model';
import { formatRateUsd, usdPerDisplayUnit } from '../../shared/utils/currency';
import { formatIsoDate } from '../../shared/utils/date';

/**
 * The Prices tab presents catalogue rates the way AI providers present
 * their pricing pages: one row per billable quantity ("Input", "Cached
 * input", "Reasoning", …), quoted per 1M tokens / per second / per item,
 * with the full rate history kept — the newest row of a (context tier,
 * service tier) pair is the current rate, older rows are history.
 */

/**
 * Display names for billable quantities, mirroring provider pricing pages.
 * Quantities without an entry here fall back to a humanized name so a new
 * catalogue dimension still renders instead of disappearing.
 */
const QUANTITY_LABELS: Readonly<Record<string, string>> = {
  billed_input_uncached: 'Input',
  billed_input_cache_read: 'Cached input',
  billed_input_cache_write: 'Cache write',
  billed_input_cache_write_1h: 'Cache write (1-hour)',
  billed_input_audio: 'Audio input',
  billed_input_audio_cache_read: 'Audio input (cached)',
  billed_input_audio_cache_write: 'Audio input (cache write)',
  billed_input_image_tokens: 'Image input',
  billed_output_text: 'Output',
  billed_output_reasoning: 'Reasoning',
  billed_output_audio: 'Audio output',
  billed_output_image_tokens: 'Image output',
  billed_output_video_tokens: 'Video output',
  billed_citation_tokens: 'Citations',
  billed_input_characters: 'Input (characters)',
  billed_output_characters: 'Output (characters)',
  billed_requests: 'Per request',
  billed_input_images: 'Input images',
  billed_output_images: 'Output images',
  billed_input_pixels: 'Input pixels',
  billed_output_pixels: 'Output pixels',
  billed_ocr_pages: 'OCR pages',
  billed_ocr_credits: 'OCR credits',
  billed_annotation_pages: 'Annotation pages',
  billed_search_queries: 'Search queries',
  billed_search_queries_low: 'Search queries (low context)',
  billed_search_queries_high: 'Search queries (high context)',
  billed_search_prompts: 'Search prompts',
  billed_search_prompts_low: 'Search prompts (low context)',
  billed_search_prompts_high: 'Search prompts (high context)',
  billed_output_milliseconds: 'Output time',
  billed_output_milliseconds_1080p: 'Output time (1080p)',
  billed_output_milliseconds_4k: 'Output time (4K)',
  billed_input_video_milliseconds: 'Video input time',
  billed_input_video_milliseconds_above_8s: 'Video input time (above 8s)',
  billed_input_video_milliseconds_above_15s: 'Video input time (above 15s)',
  billed_google_maps_queries: 'Grounding queries',
  billed_code_interpreter_sessions: 'Code interpreter sessions',
};

/**
 * Provider-style display order: input rates first, then output rates, then
 * everything else; quantities outside the list sort alphabetically last.
 */
const DIMENSION_ORDER: readonly string[] = [
  'billed_input_uncached',
  'billed_input_cache_read',
  'billed_input_cache_write',
  'billed_input_cache_write_1h',
  'billed_input_audio',
  'billed_input_audio_cache_read',
  'billed_input_audio_cache_write',
  'billed_input_image_tokens',
  'billed_input_characters',
  'billed_input_images',
  'billed_input_pixels',
  'billed_input_video_milliseconds',
  'billed_input_video_milliseconds_above_8s',
  'billed_input_video_milliseconds_above_15s',
  'billed_output_text',
  'billed_output_reasoning',
  'billed_output_audio',
  'billed_output_image_tokens',
  'billed_output_video_tokens',
  'billed_citation_tokens',
  'billed_output_characters',
  'billed_output_images',
  'billed_output_pixels',
  'billed_output_milliseconds',
  'billed_output_milliseconds_1080p',
  'billed_output_milliseconds_4k',
  'billed_requests',
  'billed_ocr_pages',
  'billed_ocr_credits',
  'billed_annotation_pages',
  'billed_search_queries',
  'billed_search_queries_low',
  'billed_search_queries_high',
  'billed_search_prompts',
  'billed_search_prompts_low',
  'billed_search_prompts_high',
  'billed_google_maps_queries',
  'billed_code_interpreter_sessions',
];

function dimensionRank(quantity: string): number {
  const index = DIMENSION_ORDER.indexOf(quantity);
  return index === -1 ? DIMENSION_ORDER.length : index;
}

function humanizeQuantity(quantity: string): string {
  const bare = quantity.startsWith('billed_') ? quantity.slice('billed_'.length) : quantity;
  return bare
    .split('_')
    .filter((word) => word.length > 0)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
}

export function quantityLabel(quantity: string): string {
  return QUANTITY_LABELS[quantity] ?? humanizeQuantity(quantity);
}

/**
 * The unit a rate is quoted per, the way providers quote it: countable
 * units per 1M, durations per second, discrete items per single item.
 */
export function priceUnitLabel(unit: string): string {
  switch (unit) {
    case 'token':
      return '1M tokens';
    case 'character':
      return '1M characters';
    case 'pixel':
      return '1M pixels';
    case 'millisecond':
      return 'second';
    case 'request':
      return 'request';
    case 'image':
      return 'image';
    case 'page':
      return 'page';
    case 'credit':
      return 'credit';
    case 'query':
      return 'query';
    case 'session':
      return 'session';
    default:
      return unit;
  }
}

export function formatPricePerUnit(pricePerKUnit: number, unit: string): string {
  return `${formatRateUsd(usdPerDisplayUnit(pricePerKUnit, unit))} / ${priceUnitLabel(unit)}`;
}

function formatCompactCount(value: number): string {
  if (value >= 1_000_000) return `${value / 1_000_000}M`;
  if (value >= 1_000) return `${value / 1_000}k`;
  return String(value);
}

/** "batch" / "context ≥ 272k tokens" / both joined; null for the base rate. */
export function variantLabel(minContextTokens: number, serviceTier: string): string | null {
  const parts: string[] = [];
  if (serviceTier !== 'default') parts.push(serviceTier);
  if (minContextTokens > 0) parts.push(`context ≥ ${formatCompactCount(minContextTokens)} tokens`);
  return parts.length > 0 ? parts.join(', ') : null;
}

export interface PriceRow {
  /**
   * Stable @for tracking key: rows of different variants (context tier,
   * service tier) share their valid_from timestamp within one updater run,
   * so validFrom alone is not unique within a dimension.
   */
  readonly key: string;
  readonly validFrom: string;
  readonly sinceText: string;
  readonly priceText: string;
  readonly variantLabel: string | null;
  readonly isCurrent: boolean;
}

export interface PriceDimension {
  readonly quantity: string;
  readonly unit: string;
  readonly label: string;
  readonly unitLabel: string;
  readonly rows: readonly PriceRow[];
}

/**
 * Group raw price rows (any order) into dimensions ordered provider-style.
 * Within a dimension the rows run newest-first per (context tier, service
 * tier) pair; the newest row of each pair is the current rate, the rest is
 * its history.
 */
export function groupPriceRows(prices: readonly ModelPriceEntry[]): readonly PriceDimension[] {
  const byDimension = new Map<string, ModelPriceEntry[]>();
  for (const price of prices) {
    // Quantity and unit names are snake_case, so a plain pipe cannot occur in them.
    const key = price.quantity + '|' + price.unit;
    const rows = byDimension.get(key);
    if (rows) {
      rows.push(price);
    } else {
      byDimension.set(key, [price]);
    }
  }

  const dimensions: PriceDimension[] = [];
  for (const rows of byDimension.values()) {
    // Every row of a group shares its quantity and unit; read them from the
    // group's first row instead of parsing the grouping key.
    const quantity = rows[0]!.quantity;
    const unit = rows[0]!.unit;
    const ordered = [...rows].sort(
      (a, b) =>
        a.min_context_tokens - b.min_context_tokens ||
        // The base rate leads its dimension; named tiers (batch, priority, …)
        // follow it in alphabetical order.
        Number(a.service_tier !== 'default') - Number(b.service_tier !== 'default') ||
        a.service_tier.localeCompare(b.service_tier) ||
        Date.parse(b.valid_from) - Date.parse(a.valid_from),
    );

    const priceRows: PriceRow[] = ordered.map((row, index) => ({
      key: row.valid_from + '|' + row.min_context_tokens + '|' + row.service_tier,
      validFrom: row.valid_from,
      sinceText: formatIsoDate(row.valid_from),
      priceText: formatPricePerUnit(row.price_per_k_unit, unit),
      variantLabel: variantLabel(row.min_context_tokens, row.service_tier),
      isCurrent:
        index === 0 ||
        ordered[index - 1]!.min_context_tokens !== row.min_context_tokens ||
        ordered[index - 1]!.service_tier !== row.service_tier,
    }));

    dimensions.push({
      quantity,
      unit,
      label: quantityLabel(quantity),
      unitLabel: priceUnitLabel(unit),
      rows: priceRows,
    });
  }

  return dimensions.sort(
    (a, b) =>
      dimensionRank(a.quantity) - dimensionRank(b.quantity) ||
      a.quantity.localeCompare(b.quantity) ||
      a.unit.localeCompare(b.unit),
  );
}

export interface PriceProviderCard {
  readonly provider: ModelProviderPrices;
  readonly dimensions: readonly PriceDimension[];
}

/**
 * One display card per cloud provider of the model. Local (logosnode)
 * providers are dropped — they bill nothing against a catalogue.
 */
export function priceProviderCards(
  providers: readonly ModelProviderPrices[],
): readonly PriceProviderCard[] {
  return providers
    .filter((provider) => provider.provider_type === 'cloud')
    .map((provider) => ({
      provider,
      dimensions: groupPriceRows(provider.prices),
    }));
}
