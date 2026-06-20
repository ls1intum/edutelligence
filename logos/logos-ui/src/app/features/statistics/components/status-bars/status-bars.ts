import { Component, Input, computed } from '@angular/core';
import { CommonModule } from '@angular/common';
import { EmptyState } from '../empty-state/empty-state';
import { STATUS_COLOR } from '../../statistics.constants';

interface StatusRow {
  label: string;
  key: 'success' | 'error' | 'timeout' | 'pending';
  value: number;
  color: string;
  pct: number;
}

@Component({
  selector: 'app-stats-status-bars',
  standalone: true,
  imports: [CommonModule, EmptyState],
  templateUrl: './status-bars.html',
  styleUrl: './status-bars.scss',
})
export class StatusBars {
  @Input() counts: Record<string, number> = {};

  // Computed property for rows with calculated percentages
  rows = computed(() => {
    const rowDefs: Array<{ label: string; key: 'success' | 'error' | 'timeout' | 'pending' }> = [
      { label: 'Success', key: 'success' },
      { label: 'Error', key: 'error' },
      { label: 'Timeout', key: 'timeout' },
      { label: 'Pending', key: 'pending' },
    ];

    const total = rowDefs.reduce((sum, def) => sum + (this.counts[def.key] ?? 0), 0);

    return rowDefs.map((def) => {
      const value = this.counts[def.key] ?? 0;
      const pct = total > 0 ? (value / total) * 100 : 0;
      return {
        label: def.label,
        key: def.key,
        value,
        color: STATUS_COLOR[def.key],
        pct,
      };
    });
  });

  // Computed property for total count
  total = computed(() => {
    const rowDefs = ['success', 'error', 'timeout', 'pending'] as const;
    return rowDefs.reduce((sum, key) => sum + (this.counts[key] ?? 0), 0);
  });
}
