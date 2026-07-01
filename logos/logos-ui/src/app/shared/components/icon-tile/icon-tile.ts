import { Component, Input, ChangeDetectionStrategy } from '@angular/core';
import { AccentColor, avatarColorName } from '../../utils/avatar';

export type TileColor = AccentColor | 'gradient';

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
  @Input() seed?: string;
  @Input() color?: TileColor;
  @Input() size = 32;

  get colorName(): TileColor {
    return this.color ?? (this.seed ? avatarColorName(this.seed) : 'purple');
  }
}
