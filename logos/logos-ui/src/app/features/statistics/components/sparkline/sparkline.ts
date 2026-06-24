import { Component, Input, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';

@Component({
  selector: 'app-stats-sparkline',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './sparkline.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrls: ['./sparkline.scss'],
})
export class SparklineComponent {
  @Input() data: number[] = [];
  @Input() color = '';

  get points(): string {
    const max = Math.max(...this.data, 0);
    if (!this.data.length || max <= 0) {
      return '';
    }

    const width = 92;
    const height = 28;

    return this.data
      .map((v, i) => {
        const x = this.data.length === 1 ? width / 2 : (i / (this.data.length - 1)) * width;
        const y = height - (v / max) * (height - 2) - 1;
        return `${x.toFixed(2)},${y.toFixed(2)}`;
      })
      .join(' ');
  }

  get shouldRender(): boolean {
    const max = Math.max(...this.data, 0);
    return this.data.length > 0 && max > 0;
  }
}
