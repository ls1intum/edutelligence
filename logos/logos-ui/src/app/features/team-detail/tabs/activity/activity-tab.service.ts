import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { RequestCursor, TeamActivityPayload } from './activity-tab.models';

/** Narrowing of the request list. `null` means "do not narrow by it". */
export interface ActivityFilter {
  userId: number | null;
  cursor: RequestCursor | null;
}

@Injectable({ providedIn: 'root' })
export class TeamActivityService {
  private http = inject(HttpClient);

  /**
   * One team's live counts, per-key spend and requests.
   *
   * The team id is in the path, not the body: the server checks access against
   * exactly the id it answers for, so there is nothing to widen by editing a
   * payload. An app admin gets a 403 for a team they do not own.
   */
  getActivity(teamId: number, days: number, filter: ActivityFilter): Promise<TeamActivityPayload> {
    return firstValueFrom(
      this.http.post<TeamActivityPayload>(`/api/logosdb/teams/${teamId}/activity`, {
        days,
        user_id: filter.userId,
        cursor_ts: filter.cursor?.ts ?? null,
        cursor_id: filter.cursor?.request_id ?? null,
      }),
    );
  }
}
