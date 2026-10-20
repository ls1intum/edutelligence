import { TestBed } from '@angular/core/testing';
import { ModelManagementService } from '../../core/services/model-management.service';
import { BenchmarkSettingsEditor } from './benchmark-settings-editor';

 describe('Worker GPU limits reload', () => {
  it('places invalid serving values beside their controls and clears them through reset', async () => {
    TestBed.configureTestingModule({ imports: [BenchmarkSettingsEditor], providers: [{
      provide: ModelManagementService, useValue: {
        getBenchmarkWorkerLimits: async () => ({ gpu_count: 1, gpu_memory_bytes: 16 * 1024 ** 3, current: {} }),
        getBenchmarkDatasetMetadata: async () => ({ dataset: 'openai/gsm8k', subset: 'main', split: 'test',
          splits: [{ subset: 'main', split: 'test' }], text_columns: ['question'] }),
      },
    }] });
    const fixture = TestBed.createComponent(BenchmarkSettingsEditor);
    fixture.componentRef.setInput('pair', { model_provider_id: 31, provider_type: 'logosnode', provider_name: 'Worker' });
    fixture.componentInstance.setServing('gpu_memory_utilization', 2);
    fixture.componentInstance.setServing('kv_cache_memory_bytes', '99G');
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
    const root = fixture.nativeElement as HTMLElement;
    const gpuError = root.querySelector('#help-gpu_memory_utilization')!;
    expect(gpuError.textContent).toContain('from 0.1 to 1');
    expect(gpuError.closest('label')?.querySelector('input')?.getAttribute('aria-invalid')).toBe('true');
    expect(root.querySelector('#help-kv_cache_memory_bytes')?.textContent).toContain('smaller than GPU memory');
    expect(root.querySelector('.serving-toolbar [role="alert"]')).toBeNull();
    const reset = Array.from(root.querySelectorAll('button')).find(button => button.textContent?.includes('Reset vLLM changes'))!;
    reset.click();
    fixture.detectChanges();
    expect(fixture.componentInstance.settings().serving_overrides).toEqual({});
    expect(root.querySelector('.serving-grid [role="alert"]')).toBeNull();
  });

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
