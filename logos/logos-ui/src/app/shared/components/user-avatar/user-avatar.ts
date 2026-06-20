import { Component, Input } from '@angular/core';
import { avatarColor } from '../../utils/avatar';

@Component({
  selector: 'app-user-avatar',
  standalone: true,
  templateUrl: './user-avatar.html',
  styleUrl: './user-avatar.scss',
})
export class UserAvatarComponent {
  @Input() username!: string;
  @Input() prename!: string;
  @Input() name!: string;
  @Input() size = 32;

  get color(): string { return avatarColor(this.username); }
  get bgColor(): string { return this.color + '26'; }
  get initials(): string {
    return `${this.prename?.[0] ?? ''}${this.name?.[0] ?? ''}`.toUpperCase();
  }
}
