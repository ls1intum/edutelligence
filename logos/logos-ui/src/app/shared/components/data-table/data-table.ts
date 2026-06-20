import { Component, Input, ViewEncapsulation } from '@angular/core';

@Component({
  selector: 'app-data-table',
  standalone: true,
  templateUrl: './data-table.html',
  styleUrl: './data-table.scss',
  encapsulation: ViewEncapsulation.None,
  host: { '[style.--data-table-grid]': 'gridCols' },
})
export class DataTableComponent {
  @Input() columns: string[] = [];
  @Input() gridCols = '';
  @Input() loading = false;
  @Input() empty = false;
  @Input() emptyMessage = 'No data.';
}
