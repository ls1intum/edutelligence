import { Component, Input, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-stats-empty-state',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './empty-state.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './empty-state.scss',
})
export class EmptyState {
  @Input() message!: string;
}
