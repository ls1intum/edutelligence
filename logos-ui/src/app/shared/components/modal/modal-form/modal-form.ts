import { Component, Input, Output, EventEmitter } from '@angular/core';
import { Dialog } from 'primeng/dialog';

@Component({
  selector: 'app-modal-form',
  standalone: true,
  imports: [Dialog],
  templateUrl: './modal-form.html',
  styleUrl: './modal-form.scss',
})
export class ModalFormComponent {
  @Input({ required: true }) visible!: boolean;
  @Input({ required: true }) title!: string;
  @Input() size: 'sm' | 'md' | 'lg' = 'md';
  @Output() visibleChange = new EventEmitter<boolean>();
}
