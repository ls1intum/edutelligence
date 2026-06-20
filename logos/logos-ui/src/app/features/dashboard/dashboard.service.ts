import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, catchError, map, of } from 'rxjs';

export interface DashboardStats {
  models: number;
  providers: number;
  requests: number;
  users: number;
  teams: number;
}

@Injectable({ providedIn: 'root' })
export class DashboardService {
  private http = inject(HttpClient);

  getStats(): Observable<DashboardStats> {
    return this.http.post<Record<string, unknown>>('/api/logosdb/generalstats', {}).pipe(
      map(response => {
        return {
          models: this.getNumericValue(response, 'models'),
          providers: this.getNumericValue(response, 'providers'),
          requests: this.getNumericValue(response, 'requests'),
          users: this.getNumericValue(response, 'api_keys'),
          teams: this.getNumericValue(response, 'teams'),
        };
      }),
      catchError(error => {
        console.error('Error fetching dashboard stats:', error);
        return of({
          models: -1,
          providers: -1,
          requests: -1,
          users: -1,
          teams: -1,
        });
      }),
    );
  }

  private getNumericValue(obj: Record<string, unknown>, key: string): number {
    const value = obj[key];
    if (value === undefined || value === null) {
      return -1;
    }
    const numValue = Number(value);
    return isNaN(numValue) ? -1 : numValue;
  }
}
