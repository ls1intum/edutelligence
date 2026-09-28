import { TestBed } from '@angular/core/testing';
import { BenchmarkBatchEditor } from './benchmark-batch-editor';
import { DEFAULT_BENCHMARK_SETTINGS } from './benchmark-settings';

describe('Attention backend batch selection', () => {
  it('builds repeated configurations from checkboxes and rejects an empty selection', async () => {
    const fixture = TestBed.createComponent(BenchmarkBatchEditor);
    fixture.componentRef.setInput('settings', DEFAULT_BENCHMARK_SETTINGS);
    fixture.componentRef.setInput('samples', 50);
    fixture.componentRef.setInput('worker', true);
    fixture.componentRef.setInput('limits', { gpu_count: 2, gpu_memory_bytes: null, current: { attention_backend: '' } });
    const editor = fixture.componentInstance;
    editor.enabled.set(true);
    editor.add('attention_backend');
    await fixture.whenStable();
    const choices = Array.from(fixture.nativeElement.querySelectorAll('.backend-choices input')) as HTMLInputElement[];
    expect(choices).toHaveLength(5);
    expect(choices[0].checked).toBe(true);
    choices[1].click();
    await fixture.whenStable();
    expect(editor.plan().batch?.configurations.map(config => config.serving_overrides['attention_backend'])).toEqual(['FLASHINFER', 'FLASH_ATTN']);
    expect(fixture.nativeElement.textContent).toContain('6 runs');
    choices[0].click();
    choices[1].click();
    await fixture.whenStable();
    expect(editor.plan().batch).toBeNull();
    expect(fixture.nativeElement.querySelector('[role="alert"]')).not.toBeNull();
  });
});
