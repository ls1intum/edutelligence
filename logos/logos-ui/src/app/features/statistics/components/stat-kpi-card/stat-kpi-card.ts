import { Component, Input } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-stats-kpi-card',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './stat-kpi-card.html',
  styleUrls: ['./stat-kpi-card.scss'],
})
export class StatKpiCardComponent {
  @Input() label!: string;
  @Input() accent = '';
  @Input() value!: string;
}
