import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { TeamActivityPayload } from './team-activity.models';

@Injectable({ providedIn: 'root' })
export class TeamActivityService {
  private http = inject(HttpClient);

  /**
   * One team's live counts and per-key spend.
   *
   * The team id is in the path, not the body: the server checks access against
   * exactly the id it answers for, so there is nothing to widen by editing a
   * payload. An app admin gets a 403 for a team they do not own.
   */
  getActivity(teamId: number, days: number): Promise<TeamActivityPayload> {
    return firstValueFrom(
      this.http.post<TeamActivityPayload>(`/api/logosdb/teams/${teamId}/activity`, { days }),
    );
  }
}
