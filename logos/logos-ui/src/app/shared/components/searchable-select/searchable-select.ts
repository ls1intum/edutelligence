import { ChangeDetectionStrategy, Component, computed, input, output, signal } from '@angular/core';
import { CdkConnectedOverlay, CdkOverlayOrigin } from '@angular/cdk/overlay';
import { A11yModule } from '@angular/cdk/a11y';
import { AppSelectOption } from '../select/select';

@Component({
  selector: 'app-searchable-select',
  imports: [CdkConnectedOverlay, CdkOverlayOrigin, A11yModule],
  templateUrl: './searchable-select.html',
  styleUrl: './searchable-select.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SearchableSelectComponent {
  readonly options = input<AppSelectOption[]>([]);
  readonly value = input<string>('');
  readonly label = input.required<string>();
  readonly disabled = input(false);
  readonly ariaLabel = input<string | undefined>(undefined);
  readonly valueChange = output<string | null>();
  readonly opened = signal(false);
  readonly query = signal('');
  readonly matches = computed(() => {
    const query = this.query().trim().toLocaleLowerCase();
    return this.options().filter((option) => option.label.toLocaleLowerCase().includes(query));
  });
  readonly summary = computed(() => {
    const value = this.value();
    return this.options().find((option) => option.value === value)?.label ?? this.emptyLabel();
  });
  readonly triggerAriaLabel = computed(() => {
    const base = this.ariaLabel() ?? `Filter by ${this.label().toLowerCase()}`;
    return `${base}: ${this.summary()}`;
  });

  private emptyLabel(): string {
    return this.options().find((option) => option.value === '')?.label ?? `All ${this.label().toLocaleLowerCase()}`;
  }

  toggle(): void {
    if (this.disabled()) return;
    this.query.set('');
    this.opened.update((open) => !open);
  }

  select(value: string): void {
    this.opened.set(false);
    this.valueChange.emit(value || null);
  }
}
