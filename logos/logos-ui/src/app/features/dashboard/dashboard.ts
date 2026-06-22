import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { IconTileComponent } from '../../shared/components/icon-tile/icon-tile';
import { Observable } from 'rxjs';
import { DashboardService, DashboardStats } from './dashboard.service';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [CommonModule, IconTileComponent],
  templateUrl: './dashboard.html',
  styleUrls: ['./dashboard.scss'],
})
export class Dashboard implements OnInit {
  private dashboardService = inject(DashboardService);

  stats$: Observable<DashboardStats | null> | undefined;
  isLoading = true;

  ngOnInit(): void {
    this.stats$ = this.dashboardService.getStats();
    this.isLoading = false;
  }
}
