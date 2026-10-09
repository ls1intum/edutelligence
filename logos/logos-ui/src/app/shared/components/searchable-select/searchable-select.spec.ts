import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { OverlayContainer } from '@angular/cdk/overlay';
import { SearchableSelectComponent } from './searchable-select';

@Component({
  imports: [SearchableSelectComponent],
  template: `<app-searchable-select
    label="Teams"
    [options]="options"
    [value]="value()"
    ariaLabel="Filter by team"
    (valueChange)="value.set($event ?? '')"
  />`,
})
class Host {
  readonly options = [
    { value: '', label: 'All teams' },
    { value: '1', label: 'alpha-team-with-a-very-long-name' },
    { value: '2', label: 'beta-team' },
  ];
  readonly value = signal('');
}

describe('searchable single-select', () => {
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

  it('searches long labels and picks one option', async () => {
    const { fixture, overlay, trigger } = await render();
    const search = overlay.querySelector<HTMLInputElement>('input[type="search"]')!;
    search.value = ' BETA ';
    search.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    const options = Array.from(
      overlay.querySelectorAll<HTMLButtonElement>('.searchable-select-option'),
    );
    expect(options).toHaveLength(1);
    expect(options[0].textContent?.trim()).toBe('beta-team');
    options[0].click();
    fixture.detectChanges();
    expect(fixture.componentInstance.value()).toBe('2');
    expect(trigger.textContent).toContain('beta-team');
    expect(overlay.querySelector('[role="listbox"]')).toBeNull();
    fixture.destroy();
  });

  it('shows an empty search result and keeps the prior selection', async () => {
    const { fixture, overlay, trigger } = await render();
    fixture.componentInstance.value.set('1');
    fixture.detectChanges();
    expect(trigger.textContent).toContain('alpha-team-with-a-very-long-name');
    const search = overlay.querySelector<HTMLInputElement>('input[type="search"]')!;
    search.value = 'missing';
    search.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    expect(overlay.textContent).toContain('No matching teams.');
    expect(fixture.componentInstance.value()).toBe('1');
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
    expect(overlay.querySelector('[role="listbox"]')).toBeNull();
    fixture.destroy();
  });

  it('caps the trigger width so long labels ellipsize', async () => {
    const { fixture, trigger } = await render();
    fixture.componentInstance.value.set('1');
    fixture.detectChanges();
    expect(getComputedStyle(trigger).maxWidth).toBe('200px');
    expect(trigger.title).toBe('alpha-team-with-a-very-long-name');
    fixture.destroy();
  });
});
