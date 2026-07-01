import { Component, Input, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-stats-kpi-card',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './stat-kpi-card.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrls: ['./stat-kpi-card.scss'],
})
export class StatKpiCardComponent {
  @Input() label!: string;
  @Input() accent = '';
  @Input() value!: string;
}
