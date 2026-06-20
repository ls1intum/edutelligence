import { Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-stats-provider-select',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './provider-select.html',
  styleUrls: ['./provider-select.scss'],
})
export class ProviderSelectComponent {
  @Input() providers: string[] = [];
  @Input() value: string | null = null;
  @Input() isOnline: (name: string) => boolean = () => true;
  @Output() valueChange = new EventEmitter<string | null>();

  onSelectChange(event: Event): void {
    const target = event.target as HTMLSelectElement;
    this.valueChange.emit(target.value || null);
  }
}
