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
  });

  async function setup() {
    const fixture = TestBed.createComponent(BenchmarkSettingsEditor);
    fixture.detectChanges();
    await fixture.whenStable();
    return fixture;
  }

  it('starts collapsed, loads on opening and closes with focus restored after selection', async () => {
    const fixture = await setup();
    expect(service.searchBenchmarkDatasets).not.toHaveBeenCalled();
    expect(fixture.nativeElement.querySelector('.dataset-grid')).toBeNull();
    const toggle: HTMLButtonElement = fixture.nativeElement.querySelector('.dataset-picker__toggle');
    toggle.click();
    await fixture.whenStable();
    expect(service.searchBenchmarkDatasets).toHaveBeenCalledWith('', undefined);
    expect(fixture.nativeElement.querySelector('[aria-pressed="true"]')?.textContent).toContain('openai/gsm8k');
    const choice = Array.from<HTMLButtonElement>(fixture.nativeElement.querySelectorAll('.dataset-grid__option'))
      .find(button => button.textContent?.includes('org/questions'))!;
    choice.click();
    await fixture.whenStable();
    expect(fixture.componentInstance.settings().dataset).toBe('org/questions');
    expect(fixture.nativeElement.querySelector('.dataset-grid')).toBeNull();
    expect(toggle.getAttribute('aria-expanded')).toBe('false');
    expect(document.activeElement).toBe(toggle);
    toggle.click();
    await fixture.whenStable();
    expect(service.searchBenchmarkDatasets).toHaveBeenCalledTimes(1);
  });

  it('discards an old page when the user changes the search', async () => {
    const fixture = await setup();
    const component = fixture.componentInstance;
    let resolve!: (value: { datasets: { id: string }[]; next_cursor: string }) => void;
    service.searchBenchmarkDatasets.mockReturnValueOnce(new Promise(r => { resolve = r; }));
    const pending = component.search('old-page');
    component.setQuery('questions');
    resolve({ datasets: [{ id: 'org/old' }], next_cursor: 'stale' });
    await pending;
    expect(component.results()).toEqual([]);
    expect(component.nextCursor()).toBeNull();
    await new Promise(resolve => setTimeout(resolve, 350));
    await fixture.whenStable();
    expect(service.searchBenchmarkDatasets).toHaveBeenLastCalledWith('questions', undefined);
    expect(component.results()).toEqual(['org/questions']);
  });

  it('appends more results without duplicates and retries the failed page', async () => {
    const fixture = await setup();
    const component = fixture.componentInstance;
    service.searchBenchmarkDatasets.mockResolvedValueOnce({ datasets: [{ id: 'org/first' }], next_cursor: 'page-2' });
    component.toggleDatasetPicker();
    await fixture.whenStable();
    service.searchBenchmarkDatasets.mockRejectedValueOnce(new Error('Offline'));
    await component.search(component.nextCursor()!);
    expect(component.results()).toEqual(['org/first']);
    expect(component.searchError()).toBeTruthy();
    service.searchBenchmarkDatasets.mockResolvedValueOnce({ datasets: [{ id: 'org/first' }, { id: 'org/second' }], next_cursor: null });
    component.retrySearch();
    await fixture.whenStable();
    expect(service.searchBenchmarkDatasets).toHaveBeenLastCalledWith('', 'page-2');
    expect(component.results()).toEqual(['org/first', 'org/second']);
    expect(component.nextCursor()).toBeNull();
  });

  it('keeps the picker open on selection errors and closes on Escape', async () => {
    const fixture = await setup();
    fixture.componentInstance.toggleDatasetPicker();
    await fixture.whenStable();
    service.getBenchmarkDatasetMetadata.mockRejectedValueOnce(new Error('Offline'));
    await fixture.componentInstance.selectDataset('org/broken');
    expect(fixture.componentInstance.pickerOpen()).toBe(true);
    expect(fixture.componentInstance.settings().dataset).toBe('openai/gsm8k');
    fixture.nativeElement.querySelector('.dataset-picker').dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await fixture.whenStable();
    expect(fixture.componentInstance.pickerOpen()).toBe(false);
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
