import { Component, Input } from '@angular/core';

@Component({
  selector: 'app-logo',
  standalone: true,
  templateUrl: './logo.html',
})
export class Logo {
  @Input() size: number = 30;
}
