import { Injectable, inject } from '@angular/core';
import { KEYCLOAK } from '../auth/keycloak';
import { HttpClient, HttpParams } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import {
  AgentCapacity,
  AgentControls,
  AgentEvent,
  AgentInstructions,
  AgentModels,
  AgentSession,
  AgentTriggers,
  AgentWorkspace,
  CreateSessionRequest,
} from '../../shared/models/agent.model';

@Injectable({ providedIn: 'root' })
export class AgentService {
  private http = inject(HttpClient);
  private keycloak = inject(KEYCLOAK);
  private static readonly BASE = '/api/agent';

  // ── workspaces ───────────────────────────────────────────────────────────
  getWorkspaces(): Promise<AgentWorkspace[]> {
    return firstValueFrom(this.http.get<AgentWorkspace[]>(`${AgentService.BASE}/workspaces`));
  }

  createWorkspace(name: string, baseBranch: string): Promise<AgentWorkspace> {
    return firstValueFrom(
      this.http.post<AgentWorkspace>(`${AgentService.BASE}/workspaces`, {
        name,
        base_branch: baseBranch,
      }),
    );
  }

  deleteWorkspace(id: number): Promise<void> {
    return firstValueFrom(this.http.delete<void>(`${AgentService.BASE}/workspaces/${id}`));
  }

  // ── sessions ─────────────────────────────────────────────────────────────
  getSessions(limit = 100): Promise<AgentSession[]> {
    const params = new HttpParams().set('limit', limit);
    return firstValueFrom(
      this.http.get<AgentSession[]>(`${AgentService.BASE}/sessions`, { params }),
    );
  }

  getSession(id: number): Promise<AgentSession> {
    return firstValueFrom(this.http.get<AgentSession>(`${AgentService.BASE}/sessions/${id}`));
  }

  createSession(body: CreateSessionRequest): Promise<AgentSession> {
    return firstValueFrom(this.http.post<AgentSession>(`${AgentService.BASE}/sessions`, body));
  }

  cancelSession(id: number): Promise<{ cancelled: boolean }> {
    return firstValueFrom(
      this.http.post<{ cancelled: boolean }>(`${AgentService.BASE}/sessions/${id}/cancel`, {}),
    );
  }

  /** Move a queued session up, down, or to the front of the queue. */
  moveInQueue(id: number, move: 'up' | 'down' | 'first'): Promise<AgentSession> {
    return firstValueFrom(
      this.http.post<AgentSession>(`${AgentService.BASE}/sessions/${id}/queue`, { move }),
    );
  }

  /** Queue the same work again — same task, workspace, branch and thread. */
  retrySession(id: number): Promise<AgentSession> {
    return firstValueFrom(
      this.http.post<AgentSession>(`${AgentService.BASE}/sessions/${id}/retry`, {}),
    );
  }

  getEvents(sessionId: number, afterId = 0): Promise<AgentEvent[]> {
    const params = new HttpParams().set('after_id', afterId);
    return firstValueFrom(
      this.http.get<AgentEvent[]>(`${AgentService.BASE}/sessions/${sessionId}/events`, { params }),
    );
  }

  /**
   * A session's events as they are written, over one long-lived response.
   *
   * Polling is what made a working session look like a stalled one: an agent
   * prints a line, and it appears whenever the next poll happens to run. The
   * runner already serves this as server-sent events; it is read here with
   * `fetch` rather than `EventSource` because the endpoint is bearer-only and
   * `EventSource` cannot carry a header. The frames are ordinary SSE.
   *
   * Yields until the session ends, the caller aborts, or the connection
   * drops — the caller decides whether a drop is worth reconnecting for.
   */
  async *streamEvents(
    sessionId: number,
    afterId: number,
    signal: AbortSignal,
  ): AsyncGenerator<AgentEvent> {
    const kc = this.keycloak;
    // Same refresh window the interceptor uses: a stream opened with a token
    // about to expire would be cut off mid-session.
    await kc.updateToken(30).catch(() => undefined);
    const response = await fetch(
      `${AgentService.BASE}/sessions/${sessionId}/stream?after_id=${afterId}`,
      {
        headers: { Authorization: `Bearer ${kc.token ?? ''}` },
        // The endpoint answers `no-cache`, which permits storing and only
        // requires revalidation. A session transcript is not something to
        // leave in a shared browser's cache.
        cache: 'no-store',
        signal,
      },
    );
    if (!response.ok || !response.body) {
      throw new Error(`event stream refused with ${response.status}`);
    }
    const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
    let buffer = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) return;
      // Server-sent events may be delimited by LF, CRLF or CR. Ours sends
      // LF today, but a proxy that rewrites line endings would otherwise
      // leave every frame in the buffer: no events, and a string that grows
      // for as long as the session runs.
      buffer += value.replace(/\r\n?/g, '\n');
      // Frames are separated by a blank line; a partial one stays in the
      // buffer until the rest of it arrives.
      let boundary = buffer.indexOf('\n\n');
      while (boundary >= 0) {
        const frame = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        // A frame may carry its payload over several `data:` lines, which
        // the specification says to join with newlines — parsing them one
        // by one would fail on exactly the long transcripts this exists for.
        const data = frame
          .split('\n')
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).replace(/^ /, ''))
          .join('\n')
          .trim();
        boundary = buffer.indexOf('\n\n');
        // The keep-alives and the closing frame carry nothing to show.
        if (!data || data === '{}') continue;
        try {
          yield JSON.parse(data) as AgentEvent;
        } catch {
          // A frame we cannot read is not worth ending the stream over;
          // the poll underneath will bring the event along.
          continue;
        }
      }
    }
  }

  /**
   * The endpoint is bearer-only, so the shot must travel through HttpClient
   * to pick up the auth header; a raw URL in a native element would 401.
   */
  getScreenshotBlob(sessionId: number, name: string): Promise<Blob> {
    return firstValueFrom(
      this.http.get(
        `${AgentService.BASE}/sessions/${sessionId}/screenshots/${encodeURIComponent(name)}`,
        { responseType: 'blob' },
      ),
    );
  }

  // ── what every session is told ───────────────────────────────────────────
  getInstructions(): Promise<AgentInstructions> {
    return firstValueFrom(
      this.http.get<AgentInstructions>(`${AgentService.BASE}/instructions`),
    );
  }

  setInstructions(body: {
    house_rules?: string;
    environment_notes?: string;
    reset_house_rules?: boolean;
    reset_environment_notes?: boolean;
  }): Promise<AgentInstructions> {
    return firstValueFrom(
      this.http.put<AgentInstructions>(`${AgentService.BASE}/instructions`, body),
    );
  }

  // ── capacity ─────────────────────────────────────────────────────────────
  getCapacity(): Promise<AgentCapacity> {
    return firstValueFrom(this.http.get<AgentCapacity>(`${AgentService.BASE}/capacity`));
  }

  /** The locally served models a session may be driven by. */
  getModels(): Promise<AgentModels> {
    return firstValueFrom(this.http.get<AgentModels>(`${AgentService.BASE}/models`));
  }

  /** Whether the runner reacts to the repository on its own. */
  getTriggers(): Promise<AgentTriggers> {
    return firstValueFrom(this.http.get<AgentTriggers>(`${AgentService.BASE}/triggers`));
  }

  /** The kill switch and the parallel ceiling, as they stand. */
  getControls(): Promise<AgentControls> {
    return firstValueFrom(this.http.get<AgentControls>(`${AgentService.BASE}/controls`));
  }

  /** Stop the runner, release it, or change how much of the platform it uses. */
  setControls(body: {
    mode?: 'running' | 'draining' | 'paused';
    reason?: string;
    max_parallel?: number | null;
    clear_max_parallel?: boolean;
  }): Promise<AgentControls> {
    return firstValueFrom(this.http.post<AgentControls>(`${AgentService.BASE}/controls`, body));
  }
}
