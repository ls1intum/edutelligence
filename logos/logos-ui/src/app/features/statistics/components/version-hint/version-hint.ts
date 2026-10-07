import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  ElementRef,
  computed,
  inject,
  input,
  signal,
  viewChild,
} from '@angular/core';

let nextBubbleId = 0;

/** How long the copy button says "Copied" before it offers to copy again. */
const COPIED_FEEDBACK_MS = 2000;

/**
 * The info icon beside a worker's version, and the card it opens.
 *
 * A mouse opens the card by hovering the icon, and the card stays open while
 * the pointer is over it, so the commit in it can be copied. Touch has no hover:
 * a tap on the icon pins the card open, and so does a click. A pinned card
 * closes on its close button, Escape, a second press on the icon, a press
 * anywhere outside, or when focus moves out of it. The icon is a disclosure
 * button, so a keyboard reaches the same card with Enter or Space.
 */
@Component({
  selector: 'app-stats-version-hint',
  standalone: true,
  templateUrl: './version-hint.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './version-hint.scss',
  host: {
    '(pointerenter)': 'onPointerEnter($event)',
    '(pointerleave)': 'onPointerLeave()',
    '(focusout)': 'onFocusOut($event)',
    '(document:pointerdown)': 'onDocumentPointerDown($event)',
    '(document:keydown.escape)': 'dismiss()',
  },
})
export class VersionHint {
  /** What the card says: what the commit is, or why there is none. */
  readonly hint = input.required<string>();
  /** The full commit, when the worker reported one: shown on its own line, with a copy button. */
  readonly commit = input<string | null>(null);

  protected readonly bubbleId = `stats-version-hint-${nextBubbleId++}`;
  /** Held open by a click or tap until it is dismissed. */
  protected readonly pinned = signal(false);
  protected readonly copied = signal(false);

  private readonly hovered = signal(false);
  /** Escape, the close button or a second click closed the card while the mouse is still over it. */
  private readonly dismissed = signal(false);
  protected readonly open = computed(() => this.pinned() || (this.hovered() && !this.dismissed()));

  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly icon = viewChild.required<ElementRef<HTMLButtonElement>>('icon');
  private readonly commitText = viewChild<ElementRef<HTMLElement>>('commitText');
  private copiedTimer: ReturnType<typeof setTimeout> | undefined;

  constructor() {
    inject(DestroyRef).onDestroy(() => clearTimeout(this.copiedTimer));
  }

  protected onPointerEnter(event: PointerEvent): void {
    // Touch and pen pointers emulate a hover that never ends, so only a mouse hovers.
    if (event.pointerType === 'mouse') this.hovered.set(true);
  }

  protected onPointerLeave(): void {
    this.hovered.set(false);
    this.dismissed.set(false);
  }

  protected toggle(): void {
    const pinning = !this.pinned();
    this.pinned.set(pinning);
    // Closing it with the mouse still over the icon has to close it, hover or not.
    this.dismissed.set(!pinning);
  }

  /** Closes the card even while the mouse is still over it (Escape, the close button). */
  protected dismiss(): void {
    if (!this.open()) return;
    const focusWasInside = this.host.nativeElement.contains(document.activeElement);
    this.pinned.set(false);
    this.dismissed.set(true);
    // The close button leaves with the card; hand a keyboard back the icon.
    if (focusWasInside) this.icon().nativeElement.focus();
  }

  protected onDocumentPointerDown(event: Event): void {
    if (this.pinned() && !this.host.nativeElement.contains(event.target as Node)) this.pinned.set(false);
  }

  protected onFocusOut(event: FocusEvent): void {
    const next = event.relatedTarget as Node | null;
    if (this.pinned() && next && !this.host.nativeElement.contains(next)) this.pinned.set(false);
  }

  protected async copy(): Promise<void> {
    const commit = this.commit();
    if (!commit) return;
    try {
      await navigator.clipboard.writeText(commit);
    } catch {
      // No clipboard (e.g. an insecure origin): select the commit instead, so
      // the keyboard's own copy shortcut still works.
      this.selectCommit();
      return;
    }
    this.copied.set(true);
    clearTimeout(this.copiedTimer);
    this.copiedTimer = setTimeout(() => this.copied.set(false), COPIED_FEEDBACK_MS);
  }

  private selectCommit(): void {
    const element = this.commitText()?.nativeElement;
    const selection = window.getSelection();
    if (!element || !selection) return;
    const range = document.createRange();
    range.selectNodeContents(element);
    selection.removeAllRanges();
    selection.addRange(range);
  }
}
