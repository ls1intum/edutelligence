import { Component, inject } from '@angular/core';
import { RouterModule } from '@angular/router';
import { AuthService } from '../../auth/services/auth.service';
import { ThemeService } from '../../services/theme.service';
import { MENU_ITEMS } from '../../../shared/constants/nav-items';
import { MenuItem } from '../../../shared/models/nav.model';
import { UserRole } from '../../auth/models/user.model';
import { Logo } from '../../../shared/components/logo/logo';

@Component({
  selector: 'app-shell',
  standalone: true,
  imports: [RouterModule, Logo],
  templateUrl: './shell.html',
  styleUrl: './shell.scss',
})
export class Shell {
  auth = inject(AuthService);
  theme = inject(ThemeService);

  visibleItems(): MenuItem[] {
    const role = this.auth.role();
    return MENU_ITEMS.filter(item => item.roles.includes(role as UserRole));
  }
}
