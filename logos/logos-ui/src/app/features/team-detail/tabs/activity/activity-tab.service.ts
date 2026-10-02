import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpResponse } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { ExportCursor, RequestCursor, TeamActivityPayload } from './activity-tab.models';

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

  /**
   * The team's request traces as a file: every request of the window, and for
   * the consented (FULL-logging) ones the stored request and response content
   * with it.
   *
   * Same gate as {@link getActivity} — the team id is in the path, and the
   * server refuses app admins who do not own the team — and the same window
   * and requester narrowing, so the export matches the list it was started
   * from. The answer is the raw file, not a parsed body: the download is cut
   * on the application server and streamed to the browser, and everything a
   * caller needs to know about the file before the first byte — its name,
   * whether it is the whole answer — travels in the response headers, which
   * is why this returns the whole response rather than its body.
   *
   * A window that outruns one file is continued, not lost: `cursor` (the
   * `X-Logos-Export-Next-Cursor` of an earlier slice, sent back verbatim)
   * makes the server send the next, older slice over the very window the
   * walk started in, instead of the newest one.
   */
  getTraceExport(
    teamId: number,
    days: number,
    userId: number | null,
    format: 'json' | 'csv',
    cursor: ExportCursor | null = null,
  ): Promise<HttpResponse<Blob>> {
    return firstValueFrom(
      this.http.post(`/api/logosdb/teams/${teamId}/activity/export`, {
        days,
        user_id: userId,
        format,
        cursor,
      }, { responseType: 'blob', observe: 'response' }),
    );
  }
}
