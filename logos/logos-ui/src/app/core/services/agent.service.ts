import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import {
  AgentCapacity,
  AgentEvent,
  AgentSession,
  AgentWorkspace,
  CreateSessionRequest,
} from '../../shared/models/agent.model';

@Injectable({ providedIn: 'root' })
export class AgentService {
  private http = inject(HttpClient);
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

  getEvents(sessionId: number, afterId = 0): Promise<AgentEvent[]> {
    const params = new HttpParams().set('after_id', afterId);
    return firstValueFrom(
      this.http.get<AgentEvent[]>(`${AgentService.BASE}/sessions/${sessionId}/events`, { params }),
    );
  }

  screenshotUrl(sessionId: number, name: string): string {
    return `${AgentService.BASE}/sessions/${sessionId}/screenshots/${encodeURIComponent(name)}`;
  }

  // ── capacity ─────────────────────────────────────────────────────────────
  getCapacity(): Promise<AgentCapacity> {
    return firstValueFrom(this.http.get<AgentCapacity>(`${AgentService.BASE}/capacity`));
  }
}
