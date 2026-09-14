import { TestBed } from '@angular/core/testing';
import { ModelManagementService } from '../../core/services/model-management.service';
import { BenchmarkSettingsEditor } from './benchmark-settings-editor';
import { ModelBenchmarkPair } from '../../shared/models/provider.model';

const metadata = (dataset = 'openai/gsm8k', subset = 'main', split = 'test') => ({
  dataset, subset, split, splits: [{ subset, split }], text_columns: ['question'],
});

describe('Benchmark dataset picker', () => {
  let service: {
    searchBenchmarkDatasets: ReturnType<typeof vi.fn>;
    getBenchmarkDatasetMetadata: ReturnType<typeof vi.fn>;
    getBenchmarkWorkerLimits: ReturnType<typeof vi.fn>;
  };
  beforeEach(() => {
    // jsdom has no media-query implementation; PrimeNG uses it for overlays.
    vi.stubGlobal('matchMedia', vi.fn().mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
    service = {
      searchBenchmarkDatasets: vi.fn().mockResolvedValue({ datasets: [{ id: 'org/questions' }] }),
      getBenchmarkDatasetMetadata: vi.fn().mockImplementation(async (...args) => metadata(...args)),
      getBenchmarkWorkerLimits: vi.fn().mockResolvedValue({ gpu_count: 4, current: {} }),
    };
    TestBed.configureTestingModule({ imports: [BenchmarkSettingsEditor], providers: [
      { provide: ModelManagementService, useValue: service },
    ] });
  });

  afterEach(() => {
    TestBed.resetTestingModule();
    vi.unstubAllGlobals();
  });

  async function setup() {
    const fixture = TestBed.createComponent(BenchmarkSettingsEditor);
    fixture.detectChanges();
    await fixture.whenStable();
    return fixture;
  }

  it('searches while typing and loads options after keyboard selection', async () => {
    const fixture = await setup();
    const input: HTMLInputElement = fixture.nativeElement.querySelector('[role="combobox"]');
    input.value = 'questions';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    await new Promise(resolve => setTimeout(resolve, 350));
    await fixture.whenStable();
    fixture.detectChanges();
    expect(service.searchBenchmarkDatasets).toHaveBeenCalledWith('questions');
    expect(input.value).toBe('questions');
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', code: 'ArrowDown', bubbles: true }));
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', bubbles: true }));
    await fixture.whenStable();
    expect(fixture.componentInstance.settings().dataset).toBe('org/questions');
    expect(service.getBenchmarkDatasetMetadata).toHaveBeenLastCalledWith('org/questions', undefined, undefined);
    expect(fixture.nativeElement.textContent).not.toContain('Reload options');
  });

  it('discards old results as soon as the query changes, including clearing it', async () => {
    const fixture = await setup();
    const component = fixture.componentInstance;
    let resolve!: (value: { datasets: { id: string }[] }) => void;
    service.searchBenchmarkDatasets.mockReturnValueOnce(new Promise(r => { resolve = r; }));
    component.setQuery('old');
    const pending = component.search();
    component.setQuery('');
    resolve({ datasets: [{ id: 'org/old' }] });
    await pending;
    expect(component.results()).toEqual([]);
    expect(component.searching()).toBe(false);
    expect(component.settings().dataset).toBe('openai/gsm8k');
  });

  it('retries the failed dataset selection without replacing the last valid settings', async () => {
    const fixture = await setup();
    service.getBenchmarkDatasetMetadata.mockRejectedValueOnce(new Error('Offline'));
    await fixture.componentInstance.inspectDataset('org/questions', 'alternate', 'train');
    fixture.detectChanges();
    expect(fixture.componentInstance.settings().dataset).toBe('openai/gsm8k');
    const retry: HTMLButtonElement = Array.from<HTMLButtonElement>(fixture.nativeElement.querySelectorAll('button'))
      .find(button => button.textContent?.includes('Retry dataset'))!;
    retry.click();
    await fixture.whenStable();
    expect(service.getBenchmarkDatasetMetadata).toHaveBeenLastCalledWith('org/questions', 'alternate', 'train');
    expect(fixture.componentInstance.settings().dataset).toBe('org/questions');
  });

  it('loads worker limits on selection and checks them again when opening serving settings', async () => {
    const fixture = await setup();
    fixture.componentRef.setInput('pair', { model_provider_id: 7, provider_type: 'logosnode' } as ModelBenchmarkPair);
    await fixture.whenStable();
    expect(service.getBenchmarkWorkerLimits).toHaveBeenCalledWith(7);
    const details: HTMLDetailsElement = fixture.nativeElement.querySelector('details:last-child');
    details.open = true;
    details.dispatchEvent(new Event('toggle'));
    await fixture.whenStable();
    expect(service.getBenchmarkWorkerLimits.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(fixture.nativeElement.textContent).not.toContain('Reload worker limits');
  });
});
