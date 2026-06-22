import { Component, Input, Output, EventEmitter } from '@angular/core';
import { Dialog } from 'primeng/dialog';

@Component({
  selector: 'app-modal-confirm',
  standalone: true,
  imports: [Dialog],
  templateUrl: './modal-confirm.html',
  styleUrl: './modal-confirm.scss',
})
export class ModalConfirmComponent {
  @Input({ required: true }) visible!: boolean;
  @Input({ required: true }) title!: string;
  @Input({ required: true }) message!: string;
  @Input() icon = 'pi-trash';
  @Input() confirmLabel = 'Confirm';
  @Input() danger = true;
  @Input() loading = false;
  @Output() visibleChange = new EventEmitter<boolean>();
  @Output() confirmed = new EventEmitter<void>();
}
