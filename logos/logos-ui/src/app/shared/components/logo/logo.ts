import { Component, Input, ChangeDetectionStrategy } from '@angular/core';

@Component({
  selector: 'app-logo',
  standalone: true,
  templateUrl: './logo.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './logo.scss',
})
export class Logo {
  @Input() size = 42;
}
