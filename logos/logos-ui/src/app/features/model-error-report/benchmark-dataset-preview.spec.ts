import { TestBed } from '@angular/core/testing';
import { ModelManagementService } from '../../core/services/model-management.service';
import { BenchmarkSettingsEditor } from './benchmark-settings-editor';
import { DatasetMetadata, datasetViewerUrl } from './benchmark-settings';

const metadata: DatasetMetadata = {
  dataset: 'openai/gsm8k', subset: 'main', split: 'test',
  splits: [{ subset: 'main', split: 'test' }, { subset: 'main', split: 'train' }],
  text_columns: ['question', 'answer'], preview_columns: ['question', 'answer'],
  preview_rows: [{ row_index: 0, cells: { question: '<b>How many?</b>', answer: 'Four.\n#### 4' }, truncated_columns: ['answer'] }],
};

describe('Benchmark dataset preview', () => {
  let service: { getBenchmarkDatasetMetadata: ReturnType<typeof vi.fn> };
  beforeEach(() => {
    service = { getBenchmarkDatasetMetadata: vi.fn().mockResolvedValue(structuredClone(metadata)) };
    TestBed.configureTestingModule({ imports: [BenchmarkSettingsEditor], providers: [
      { provide: ModelManagementService, useValue: service },
    ] });
  });

  it('renders questions and reference answers as plain text with a matching viewer link', async () => {
    const fixture = TestBed.createComponent(BenchmarkSettingsEditor);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    const element: HTMLElement = fixture.nativeElement;
    expect(element.querySelector('.dataset-preview__rows')?.textContent).toContain('<b>How many?</b>');
    expect(element.querySelector('.dataset-preview__rows b')).toBeNull();
    expect(element.querySelector('.dataset-preview__rows')?.textContent).toContain('Four.');
    expect(element.textContent).toContain('Excerpt');
    expect(element.querySelector('a')?.href).toBe('https://huggingface.co/datasets/openai/gsm8k/viewer/main/test');
    expect(element.querySelector('a')?.rel).toContain('noopener');
    expect(service.getBenchmarkDatasetMetadata).toHaveBeenCalledTimes(1);
  });

  it('hides previous examples during split loading and ignores a late previous response', async () => {
    const fixture = TestBed.createComponent(BenchmarkSettingsEditor);
    fixture.detectChanges();
    await fixture.whenStable();
    let resolve!: (value: DatasetMetadata) => void;
    service.getBenchmarkDatasetMetadata.mockImplementationOnce(() => new Promise(r => { resolve = r; }));
    const previous = fixture.componentInstance.inspectDataset(metadata.dataset, 'main', 'train');
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('Loading examples');
    expect(fixture.nativeElement.querySelector('.dataset-preview__rows')).toBeNull();
    await fixture.componentInstance.inspectDataset(metadata.dataset, 'main', 'test');
    resolve({ ...metadata, split: 'train' });
    await previous;
    expect(fixture.componentInstance.settings().split).toBe('test');
    expect(fixture.componentInstance.metadata()?.split).toBe('test');
  });

  it('keeps the viewer link available when the preview API fails', async () => {
    service.getBenchmarkDatasetMetadata.mockRejectedValue(new Error('Offline'));
    const fixture = TestBed.createComponent(BenchmarkSettingsEditor);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('No preview available');
    expect(fixture.nativeElement.querySelector('a')?.href).toContain('/viewer/main/test');
  });

  it('escapes configuration and split URL segments without changing the destination', () => {
    expect(datasetViewerUrl({ dataset: 'org/data', subset: 'a/b', split: 'test?x=1#here' }))
      .toBe('https://huggingface.co/datasets/org/data/viewer/a%2Fb/test%3Fx%3D1%23here');
  });
});
