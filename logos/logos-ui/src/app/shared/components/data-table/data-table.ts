import { Component, EventEmitter, Input, Output, ViewEncapsulation, ChangeDetectionStrategy } from '@angular/core';

@Component({
  selector: 'app-data-table',
  standalone: true,
  templateUrl: './data-table.html',
  styleUrl: './data-table.scss',
  encapsulation: ViewEncapsulation.None,
  changeDetection: ChangeDetectionStrategy.Eager,
  host: { '[style.--data-table-grid]': 'gridCols' },
})
export class DataTableComponent {
  @Input() columns: string[] = [];
  @Input() gridCols = '';
  @Input() loading = false;
  @Input() empty = false;
  @Input() emptyMessage = 'No data.';

  /** Index of the column whose header toggles sorting (-1: no sortable column). */
  @Input() sortableColumn = -1;
  /** Current sort direction of the sortable column (null: unsorted). */
  @Input() sortDirection: 'asc' | 'desc' | null = null;
  /** Emitted when the sortable column header is clicked. */
  @Output() sortToggle = new EventEmitter<void>();

  get sortIcon(): string {
    if (this.sortDirection === 'asc') return 'pi-sort-up';
    if (this.sortDirection === 'desc') return 'pi-sort-down';
    return 'pi-sort';
  }
}
