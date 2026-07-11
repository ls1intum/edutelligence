import { Component, EventEmitter, Input, Output, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';

export interface AppSelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

@Component({
  selector: 'app-select',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './select.html',
  styleUrls: ['./select.scss'],
  changeDetection: ChangeDetectionStrategy.Eager,
})
export class SelectComponent {
  @Input() options: AppSelectOption[] = [];
  @Input() value: string | null = null;
  @Input() disabled = false;
  @Input() compact = false;
  @Input() collapseWhenSingle = false;
  @Input() id?: string;
  @Input() ariaLabel?: string;
  @Output() valueChange = new EventEmitter<string | null>();

  get selectedLabel(): string {
    const match = this.options.find((o) => o.value === (this.value ?? ''));
    return match ? match.label : '—';
  }

  onChange(event: Event): void {
    const target = event.target as HTMLSelectElement;
    this.valueChange.emit(target.value || null);
  }
}
