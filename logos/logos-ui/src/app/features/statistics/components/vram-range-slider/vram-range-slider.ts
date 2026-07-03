import {
  Component,
  ElementRef,
  EventEmitter,
  Input,
  Output,
  PLATFORM_ID,
  inject,
  ChangeDetectionStrategy,
} from '@angular/core';
import { isPlatformBrowser } from '@angular/common';

@Component({
  selector: 'app-stats-vram-range-slider',
  standalone: true,
  templateUrl: './vram-range-slider.html',
  styleUrl: './vram-range-slider.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class VramRangeSliderComponent {
  @Input({ required: true }) min!: number;    // timestamp ms
  @Input({ required: true }) max!: number;    // timestamp ms
  @Input({ required: true }) start!: number;  // current window start ms
  @Input({ required: true }) end!: number;    // current window end ms
  @Output() windowChange = new EventEmitter<{ start: number; end: number }>();

  private readonly isBrowser = isPlatformBrowser(inject(PLATFORM_ID));
  private readonly host = inject(ElementRef<HTMLElement>);

  // Derived CSS percentages for positioning
  get startPct(): number { return this.toPercent(this.start); }
  get endPct(): number { return this.toPercent(this.end); }

  private toPercent(val: number): number {
    const range = this.max - this.min;
    if (range === 0) return 0;
    return Math.max(0, Math.min(100, (val - this.min) / range * 100));
  }

  onStartHandleDrag(event: MouseEvent): void {
    if (!this.isBrowser) return;
    event.preventDefault();
    event.stopPropagation();
    const startX = event.clientX;
    const startVal = this.start;
    const onMove = (e: MouseEvent) => {
      const rect = this.host.nativeElement.getBoundingClientRect();
      const dx = (e.clientX - startX) / rect.width;
      const range = this.max - this.min;
      const newStart = Math.max(this.min, Math.min(this.end - range * 0.05, startVal + dx * range));
      this.windowChange.emit({ start: newStart, end: this.end });
    };
    const onUp = () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }

  onEndHandleDrag(event: MouseEvent): void {
    if (!this.isBrowser) return;
    event.preventDefault();
    event.stopPropagation();
    const startX = event.clientX;
    const startVal = this.end;
    const onMove = (e: MouseEvent) => {
      const rect = this.host.nativeElement.getBoundingClientRect();
      const dx = (e.clientX - startX) / rect.width;
      const range = this.max - this.min;
      const newEnd = Math.max(this.start + range * 0.05, Math.min(this.max, startVal + dx * range));
      this.windowChange.emit({ start: this.start, end: newEnd });
    };
    const onUp = () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }

  onBandDrag(event: MouseEvent): void {
    if (!this.isBrowser) return;
    event.preventDefault();
    event.stopPropagation();
    const startX = event.clientX;
    const startStart = this.start;
    const startEnd = this.end;
    const onMove = (e: MouseEvent) => {
      const rect = this.host.nativeElement.getBoundingClientRect();
      const dx = (e.clientX - startX) / rect.width;
      const range = this.max - this.min;
      let newStart = startStart + dx * range;
      let newEnd = startEnd + dx * range;
      if (newStart < this.min) { newEnd += this.min - newStart; newStart = this.min; }
      if (newEnd > this.max) { newStart -= newEnd - this.max; newEnd = this.max; }
      this.windowChange.emit({ start: newStart, end: newEnd });
    };
    const onUp = () => {
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }
}
