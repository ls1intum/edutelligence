import { Component, OnInit, inject, signal, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { IconTileComponent } from '../../shared/components/icon-tile/icon-tile';
import { DashboardService, DashboardStats } from './dashboard.service';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, IconTileComponent],
  templateUrl: './dashboard.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrls: ['./dashboard.scss'],
})
export class Dashboard implements OnInit {
  private dashboardService = inject(DashboardService);

  stats = signal<DashboardStats | null>(null);
  loading = signal(true);

  async ngOnInit(): Promise<void> {
    try {
      const stats = await this.dashboardService.getStats();
      this.stats.set(stats);
    } finally {
      this.loading.set(false);
    }
  }
}
