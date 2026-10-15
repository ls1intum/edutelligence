import { TestBed } from '@angular/core/testing';
import { ModelManagementService } from '../../core/services/model-management.service';
import { BenchmarkSettingsEditor } from './benchmark-settings-editor';

 describe('Worker GPU limits reload', () => {
  it.each(['unknown', 'error'])('reloads after %s without clearing requested settings', async (initial) => {
    const getLimits = vi.fn();
    if (initial === 'unknown') getLimits.mockResolvedValueOnce({ gpu_count: null, current: {} });
    else getLimits.mockRejectedValueOnce(new Error('Worker offline'));
    getLimits.mockResolvedValue({ gpu_count: 2, gpu_memory_bytes: null, current: {} });
    TestBed.configureTestingModule({ imports: [BenchmarkSettingsEditor], providers: [{
      provide: ModelManagementService, useValue: {
        getBenchmarkWorkerLimits: getLimits,
        getBenchmarkDatasetMetadata: async () => ({ dataset: 'openai/gsm8k', subset: 'main', split: 'test',
          splits: [{ subset: 'main', split: 'test' }], text_columns: ['question'] }),
      },
    }] });
    const fixture = TestBed.createComponent(BenchmarkSettingsEditor);
    fixture.componentRef.setInput('pair', { model_provider_id: 31, provider_type: 'logosnode', provider_name: 'Worker' });
    fixture.componentInstance.setServing('tensor_parallel_size', 2);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    const button = Array.from(fixture.nativeElement.querySelectorAll('button') as NodeListOf<HTMLButtonElement>)
      .find(b => b.textContent?.trim() === 'Reload GPU limits')!;
    expect(button).toBeTruthy();
    expect(button.disabled).toBe(false);
    expect(fixture.componentInstance.validationErrors().length).toBeGreaterThan(0);
    button.click();
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(getLimits).toHaveBeenCalledTimes(2);
    expect(fixture.componentInstance.limits()?.gpu_count).toBe(2);
    expect(fixture.componentInstance.validationErrors()).toEqual([]);
    expect(fixture.componentInstance.settings().serving_overrides['tensor_parallel_size']).toBe(2);
  });
});
