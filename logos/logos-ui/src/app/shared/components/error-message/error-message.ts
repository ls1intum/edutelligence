import { Component, Input } from '@angular/core';

@Component({
  selector: 'app-error-message',
  standalone: true,
  templateUrl: './error-message.html',
  styleUrl: './error-message.scss',
  host: {
    role: 'alert',
    '[class]': 'variant',
  },
})
export class ErrorMessageComponent {
  @Input({ required: true }) message!: string;
  @Input() variant: 'banner' | 'dialog' | 'tab' = 'dialog';
}
