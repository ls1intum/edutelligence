import { Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { describe, expect, it } from 'vitest';

import { AppSelectOption, SelectComponent } from './select';

@Component({
  standalone: true,
  imports: [SelectComponent],
  template: `<app-select
    [options]="options()"
    [value]="value()"
    (valueChange)="value.set($any($event))"
  />`,
})
class Host {
  readonly options = signal<AppSelectOption[]>([
    { value: 'logosnode', label: 'logosnode' },
    { value: 'cloud', label: 'cloud' },
  ]);
  readonly value = signal<string | null>('cloud');
}

function nativeSelect(fixture: ComponentFixture<Host>): HTMLSelectElement {
  return fixture.nativeElement.querySelector('select') as HTMLSelectElement;
}

describe('SelectComponent', () => {
  async function render(): Promise<ComponentFixture<Host>> {
    await TestBed.configureTestingModule({ imports: [Host] }).compileComponents();
    const fixture = TestBed.createComponent(Host);
    fixture.detectChanges();
    return fixture;
  }

  it('shows the bound value on first render, not the first option', async () => {
    // Regression: the <select>'s own [value] binding runs before the @for has
    // produced any <option>, so the assignment is dropped and the browser
    // falls back to index 0. A provider dialog opened on "cloud" then read
    // "logosnode" while the component state said otherwise.
    const fixture = await render();
    expect(nativeSelect(fixture).value).toBe('cloud');
  });

  it('follows the bound value when the parent changes it', async () => {
    const fixture = await render();
    fixture.componentInstance.value.set('logosnode');
    fixture.detectChanges();
    expect(nativeSelect(fixture).value).toBe('logosnode');
  });

  it('shows the bound value when the options arrive after it', async () => {
    // The cloud-provider-type dropdown recomputes its options from the
    // selected provider type, so a value can be bound before its option list.
    await TestBed.configureTestingModule({ imports: [Host] }).compileComponents();
    const fixture = TestBed.createComponent(Host);
    fixture.componentInstance.options.set([]);
    fixture.componentInstance.value.set('groq');
    fixture.detectChanges();

    fixture.componentInstance.options.set([
      { value: 'azure', label: 'azure' },
      { value: 'groq', label: 'groq' },
    ]);
    fixture.detectChanges();
    expect(nativeSelect(fixture).value).toBe('groq');
  });

  it('emits the picked value', async () => {
    const fixture = await render();
    const select = nativeSelect(fixture);
    select.value = 'logosnode';
    select.dispatchEvent(new Event('change'));
    fixture.detectChanges();
    expect(fixture.componentInstance.value()).toBe('logosnode');
  });
});
