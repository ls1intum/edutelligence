import { Component, Input, Output, EventEmitter, ChangeDetectionStrategy } from '@angular/core';
import { TumUiDialogComponent, type TumUiDialogSize } from '@tumaet/ui-angular';

const SIZE_MAP: Record<'sm' | 'md' | 'lg' | 'xl', TumUiDialogSize> = {
  sm: 'small',
  md: 'medium',
  lg: 'large',
  xl: 'full',
};

@Component({
  selector: 'app-modal-form',
  standalone: true,
  imports: [TumUiDialogComponent],
  templateUrl: './modal-form.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './modal-form.scss',
})
export class ModalFormComponent {
  @Input({ required: true }) visible!: boolean;
  @Input({ required: true }) title!: string;
  @Input() size: 'sm' | 'md' | 'lg' | 'xl' = 'md';
  @Output() visibleChange = new EventEmitter<boolean>();

  protected get tumUiSize(): TumUiDialogSize {
    return SIZE_MAP[this.size];
  }
}
