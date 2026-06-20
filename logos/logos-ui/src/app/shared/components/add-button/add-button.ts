import { Component, Input } from '@angular/core';

@Component({
  selector: 'app-add-button',
  standalone: true,
  templateUrl: './add-button.html',
  styleUrl: './add-button.scss',
})
export class AddButton {
  @Input() disabled = false;
  @Input() size: 'sm' | 'md' = 'md';
}
