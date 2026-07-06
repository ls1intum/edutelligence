import { Component, Input, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-stats-chart-panel',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './chart-panel.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './chart-panel.scss',
})
export class ChartPanel {
  @Input() title!: string;
  @Input() subtitle?: string;
}
