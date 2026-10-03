import { ComponentFixture, TestBed } from '@angular/core/testing';
import { vi } from 'vitest';

import { VersionHint } from './version-hint';

const COMMIT = 'a3f9c21e0b7d4f65a1c2d3e4f5061728394a5b6c';
const HINT = "Commit this worker's image was built from:";

/**
 * A pointer event of the given kind. The test DOM may not implement
 * PointerEvent, so this is a plain event carrying the one field the component
 * reads.
 */
function pointerEvent(type: string, pointerType: 'mouse' | 'touch'): Event {
  const event = new MouseEvent(type, { bubbles: true });
  Object.defineProperty(event, 'pointerType', { value: pointerType });
  return event;
}

/**
 * The card behind the info icon next to a worker's version.
 *
 * A mouse hovers it open and it stays open while the pointer is over it, which
 * is what lets the commit in it be copied. Touch has no hover, so a tap pins it
 * open and it has to be dismissable without one: its close button, Escape, a
 * second press on the icon, a press outside, or focus leaving it.
 */
describe('VersionHint', () => {
  let fixture: ComponentFixture<VersionHint>;
  let host: HTMLElement;

  const icon = () => host.querySelector<HTMLButtonElement>('.hint__icon')!;
  const bubble = () => host.querySelector<HTMLElement>('.hint__bubble')!;
  const isOpen = () => bubble().classList.contains('hint__bubble--open');
  const closeButton = () => host.querySelector<HTMLButtonElement>('.hint__close');
  const copyButton = () => host.querySelector<HTMLButtonElement>('.btn-copy');
  const settle = () => fixture.detectChanges();

  function render(commit: string | null = COMMIT, hint: string = HINT): void {
    fixture = TestBed.createComponent(VersionHint);
    fixture.componentRef.setInput('hint', hint);
    fixture.componentRef.setInput('commit', commit);
    host = fixture.nativeElement;
    fixture.detectChanges();
  }

  function stubClipboard(writeText: () => Promise<void>): void {
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
  }

  beforeEach(async () => {
    await TestBed.configureTestingModule({ imports: [VersionHint] }).compileComponents();
  });

  afterEach(() => {
    vi.useRealTimers();
    delete (navigator as unknown as { clipboard?: unknown }).clipboard;
    window.getSelection()?.removeAllRanges();
  });

  it('stays closed until the mouse is over the icon, and closes again when it leaves', () => {
    render();
    expect(isOpen()).toBe(false);
    expect(icon().getAttribute('aria-expanded')).toBe('false');

    host.dispatchEvent(pointerEvent('pointerenter', 'mouse'));
    settle();
    expect(isOpen()).toBe(true);
    expect(icon().getAttribute('aria-expanded')).toBe('true');

    host.dispatchEvent(pointerEvent('pointerleave', 'mouse'));
    settle();
    expect(isOpen()).toBe(false);
  });

  it('does not treat the hover a touch screen emulates as a hover', () => {
    render();
    host.dispatchEvent(pointerEvent('pointerenter', 'touch'));
    settle();
    expect(isOpen()).toBe(false);
  });

  it('pins open on a tap, with a close button that closes it', () => {
    render();
    expect(closeButton()).toBeNull();

    icon().click();
    settle();
    expect(isOpen()).toBe(true);
    expect(closeButton()).not.toBeNull();

    closeButton()!.click();
    settle();
    expect(isOpen()).toBe(false);
    expect(closeButton()).toBeNull();
  });

  it('stays open after the mouse leaves once it was pinned', () => {
    render();
    host.dispatchEvent(pointerEvent('pointerenter', 'mouse'));
    icon().click();
    host.dispatchEvent(pointerEvent('pointerleave', 'mouse'));
    settle();
    expect(isOpen()).toBe(true);
  });

  it('closes a pinned card with a second click on the icon, even with the mouse still over it', () => {
    render();
    host.dispatchEvent(pointerEvent('pointerenter', 'mouse'));
    icon().click();
    settle();
    expect(isOpen()).toBe(true);

    icon().click();
    settle();
    expect(isOpen()).toBe(false);
  });

  it('closes on Escape even while the mouse is still over it, and opens again on the next hover', () => {
    render();
    host.dispatchEvent(pointerEvent('pointerenter', 'mouse'));
    settle();
    expect(isOpen()).toBe(true);

    document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    settle();
    expect(isOpen()).toBe(false);

    host.dispatchEvent(pointerEvent('pointerleave', 'mouse'));
    host.dispatchEvent(pointerEvent('pointerenter', 'mouse'));
    settle();
    expect(isOpen()).toBe(true);
  });

  it('closes a pinned card on a press outside, but not on a press inside', () => {
    render();
    icon().click();
    settle();

    bubble().dispatchEvent(pointerEvent('pointerdown', 'touch'));
    settle();
    expect(isOpen()).toBe(true);

    document.body.dispatchEvent(pointerEvent('pointerdown', 'touch'));
    settle();
    expect(isOpen()).toBe(false);
  });

  it('closes a pinned card when focus moves out of it, but not within it', () => {
    render();
    icon().click();
    settle();

    host.dispatchEvent(new FocusEvent('focusout', { bubbles: true, relatedTarget: copyButton() }));
    settle();
    expect(isOpen()).toBe(true);

    host.dispatchEvent(new FocusEvent('focusout', { bubbles: true, relatedTarget: document.body }));
    settle();
    expect(isOpen()).toBe(false);
  });

  it('copies the full commit and says so for a moment', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    stubClipboard(writeText);
    vi.useFakeTimers();
    render();
    icon().click();
    settle();
    expect(copyButton()!.textContent!.trim()).toBe('Copy');

    copyButton()!.click();
    await vi.advanceTimersByTimeAsync(0);
    settle();
    expect(writeText).toHaveBeenCalledWith(COMMIT);
    expect(copyButton()!.textContent!.trim()).toBe('Copied');
    expect(host.querySelector('.hint__sr-only')!.textContent).toContain('copied');

    await vi.advanceTimersByTimeAsync(2000);
    settle();
    expect(copyButton()!.textContent!.trim()).toBe('Copy');
  });

  it('selects the commit when the clipboard cannot be written', async () => {
    stubClipboard(vi.fn().mockRejectedValue(new Error('denied')));
    render();
    icon().click();
    settle();

    copyButton()!.click();
    await Promise.resolve();
    await Promise.resolve();
    settle();
    expect(window.getSelection()!.toString()).toBe(COMMIT);
    expect(copyButton()!.textContent!.trim()).toBe('Copy');
  });

  it('shows the commit on a line of its own, apart from the sentence', () => {
    render();
    expect(host.querySelector('.hint__text')!.textContent).toBe(HINT);
    expect(host.querySelector('.hint__commit')!.textContent).toBe(COMMIT);
  });

  it('has nothing to copy for a worker without a commit, and only explains why', () => {
    render(null, 'Built outside CI, so no commit was recorded.');
    expect(host.querySelector('.hint__commit')).toBeNull();
    expect(copyButton()).toBeNull();
    expect(host.querySelector('.hint__text')!.textContent).toBe('Built outside CI, so no commit was recorded.');
  });
});
