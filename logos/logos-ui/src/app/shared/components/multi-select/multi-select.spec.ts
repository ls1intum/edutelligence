import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { OverlayContainer } from '@angular/cdk/overlay';
import { MultiSelectComponent } from './multi-select';

@Component({
  imports: [MultiSelectComponent],
  template: `<app-multi-select
    label="Models"
    [options]="options"
    [values]="values()"
    (valuesChange)="values.set($event)"
  />`,
})
class Host {
  readonly options = [
    { value: '1', label: 'org/very-long-model-name-alpha' },
    { value: '2', label: 'org/very-long-model-name-beta' },
  ];
  readonly values = signal<string[]>([]);
}

describe('searchable multi-select', () => {
  async function render() {
    await TestBed.configureTestingModule({ imports: [Host] }).compileComponents();
    const fixture = TestBed.createComponent(Host);
    fixture.detectChanges();
    const trigger: HTMLButtonElement = fixture.nativeElement.querySelector('button');
    trigger.focus();
    trigger.click();
    fixture.detectChanges();
    const overlay = TestBed.inject(OverlayContainer).getContainerElement();
    return { fixture, trigger, overlay };
  }

  it('searches long labels without dropping a hidden selection', async () => {
    const { fixture, overlay } = await render();
    const checkboxes = () =>
      Array.from(overlay.querySelectorAll<HTMLInputElement>('input[type="checkbox"]'));
    checkboxes()[0].click();
    fixture.detectChanges();
    const search = overlay.querySelector<HTMLInputElement>('input[type="search"]')!;
    search.value = ' BETA ';
    search.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    expect(checkboxes()).toHaveLength(1);
    checkboxes()[0].click();
    fixture.detectChanges();
    expect(fixture.componentInstance.values()).toEqual(['1', '2']);
    expect(fixture.nativeElement.textContent).toContain('2 models');
    search.value = '';
    search.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    expect(checkboxes().every((checkbox) => checkbox.checked)).toBe(true);
    checkboxes()[0].click();
    fixture.detectChanges();
    expect(fixture.componentInstance.values()).toEqual(['2']);
    expect(fixture.nativeElement.textContent).toContain('org/very-long-model-name-beta');
    fixture.destroy();
  });

  it('shows an empty search result and clears the whole selection', async () => {
    const { fixture, overlay } = await render();
    fixture.componentInstance.values.set(['1']);
    const search = overlay.querySelector<HTMLInputElement>('input[type="search"]')!;
    search.value = 'missing';
    search.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    expect(overlay.textContent).toContain('No matching models.');
    overlay.querySelector<HTMLButtonElement>('.multi-select-clear')!.click();
    fixture.detectChanges();
    expect(fixture.componentInstance.values()).toEqual([]);
    expect(fixture.nativeElement.textContent).toContain('All models');
    fixture.destroy();
  });

  it('closes on Escape and restores the trigger focus', async () => {
    const { fixture, trigger, overlay } = await render();
    overlay
      .querySelector('input')!
      .dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    fixture.detectChanges();
    expect(document.activeElement).toBe(trigger);
    expect(trigger.getAttribute('aria-expanded')).toBe('false');
    expect(overlay.querySelector('[role="dialog"]')).toBeNull();
    fixture.destroy();
  });
});
