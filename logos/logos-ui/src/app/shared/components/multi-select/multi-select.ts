import { ChangeDetectionStrategy, Component, computed, input, output, signal } from '@angular/core';
import { CdkConnectedOverlay, CdkOverlayOrigin } from '@angular/cdk/overlay';
import { A11yModule } from '@angular/cdk/a11y';
import { AppSelectOption } from '../select/select';

@Component({
  selector: 'app-multi-select',
  imports: [CdkConnectedOverlay, CdkOverlayOrigin, A11yModule],
  templateUrl: './multi-select.html',
  styleUrl: './multi-select.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MultiSelectComponent {
  readonly options = input<AppSelectOption[]>([]);
  readonly values = input<string[]>([]);
  readonly label = input.required<string>();
  readonly valuesChange = output<string[]>();
  readonly opened = signal(false);
  readonly query = signal('');
  readonly matches = computed(() => {
    const query = this.query().trim().toLocaleLowerCase();
    return this.options().filter((option) => option.label.toLocaleLowerCase().includes(query));
  });
  readonly summary = computed(() => {
    const values = this.values();
    if (!values.length) return `All ${this.label().toLocaleLowerCase()}`;
    if (values.length === 1)
      return this.options().find((option) => option.value === values[0])?.label ?? values[0];
    return `${values.length} ${this.label().toLocaleLowerCase()}`;
  });

  toggle(): void {
    this.query.set('');
    this.opened.update((open) => !open);
  }

  select(value: string): void {
    const values = this.values();
    this.valuesChange.emit(
      values.includes(value) ? values.filter((item) => item !== value) : [...values, value],
    );
  }
}
