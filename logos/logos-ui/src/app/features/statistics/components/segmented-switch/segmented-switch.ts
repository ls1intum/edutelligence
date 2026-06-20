import { Component, EventEmitter, Input, Output } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-stats-segmented-switch',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './segmented-switch.html',
  styleUrls: ['./segmented-switch.scss'],
})
export class SegmentedSwitchComponent {
  @Input() options: { value: string; label: string }[] = [];
  @Input() value!: string;
  @Output() valueChange = new EventEmitter<string>();
}
