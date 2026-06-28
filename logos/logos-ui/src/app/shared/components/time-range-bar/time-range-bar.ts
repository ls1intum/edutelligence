import { Component, EventEmitter, Input, Output, ChangeDetectionStrategy } from '@angular/core';
import { TimePreset, PRESETS, calendarRange, periodLabel } from '../../utils/time-range';

@Component({
  selector: 'app-time-range-bar',
  standalone: true,
  templateUrl: './time-range-bar.html',
  styleUrl: './time-range-bar.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TimeRangeBarComponent {
  @Input({ required: true }) preset!: TimePreset;
  @Input() offset = 0;
  @Input() presets: ReadonlyArray<{ value: TimePreset; label: string }> = PRESETS;

  @Output() presetChange = new EventEmitter<TimePreset>();
  @Output() offsetChange = new EventEmitter<number>();

  get periodLabel(): string {
    return periodLabel(this.preset, this.offset, calendarRange(this.preset, this.offset));
  }

  setPreset(p: TimePreset): void {
    if (p === this.preset) return;
    this.presetChange.emit(p);
    this.offsetChange.emit(0); // new preset resets to the current period
  }

  navPrev(): void {
    this.offsetChange.emit(this.offset + 1);
  }

  navNext(): void {
    if (this.offset > 0) this.offsetChange.emit(this.offset - 1);
  }
}
