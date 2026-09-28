import { TestBed } from '@angular/core/testing';
import { BenchmarkRunFailure } from './benchmark-run-failure';

describe('Benchmark failure details', () => {
  it('shows the failed backend, repetition and root cause without interpreting the return code', async () => {
    const fixture = TestBed.createComponent(BenchmarkRunFailure);
    fixture.componentRef.setInput('run', {
      error_message: 'return_code=1',
      result: { configuration_index: 2, repetition: 1, completed_runs: 3, total_runs: 9,
        failure: { model: 'org/model', attention_backend: 'FLASHINFER', settings: { samples: 5 },
          details: 'return_code=1. Cause: ValueError: unsupported head size. Recent logs: shutdown' } },
    });
    await fixture.whenStable();
    expect(fixture.nativeElement.textContent).toContain('FLASHINFER');
    expect(fixture.nativeElement.textContent).toContain('Configuration 2 · repetition 1');
    expect(fixture.componentInstance.summary()).toBe('ValueError: unsupported head size.');
  });
  it('explains that historical truncated errors have no recorded root cause', async () => {
    const fixture = TestBed.createComponent(BenchmarkRunFailure);
    fixture.componentRef.setInput('run', { error_message: 'vLLM exited during startup (return_code=1). Engine core initialization failed', result: {} });
    await fixture.whenStable();
    expect(fixture.componentInstance.summary()).toContain('does not identify the cause');
    expect(fixture.nativeElement.querySelector('pre').textContent).toContain('return_code=1');
  });
});
