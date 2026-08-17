import { Component, Input, ChangeDetectionStrategy } from '@angular/core';

@Component({
  selector: 'app-icon-tile',
  standalone: true,
  templateUrl: './icon-tile.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './icon-tile.scss',
})
export class IconTileComponent {
  @Input() label?: string;
  @Input() icon?: string;
  @Input() size = 32;
}
