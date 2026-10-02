import {
  Component,
  Input,
  OnChanges,
  signal,
  inject,
  ChangeDetectionStrategy,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DataTableComponent } from '../../../../shared/components/data-table/data-table';
import { ModalFormComponent } from '../../../../shared/components/modal/modal-form/modal-form';
import { ModalConfirmComponent } from '../../../../shared/components/modal/modal-confirm/modal-confirm';
import { ErrorMessageComponent } from '../../../../shared/components/error-message/error-message';
import { TeamManagementService } from '../../../../core/services/team-management.service';
import { TeamRepository } from '../../../../shared/models/team.model';

/**
 * Team → Repositories.
 *
 * Links GitHub repositories for AI-workflow analysis. Owners can store a
 * deploy key for private repos, run a heuristic scan, or queue an agent
 * analysis session.
 */
@Component({
  selector: 'app-repositories-tab',
  standalone: true,
  imports: [
    FormsModule,
    DataTableComponent,
    ModalFormComponent,
    ModalConfirmComponent,
    ErrorMessageComponent,
  ],
  templateUrl: './repositories-tab.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './repositories-tab.scss',
})
export class RepositoriesTabComponent implements OnChanges {
  @Input() teamId!: number;
  @Input() canEdit = false;

  private teamService = inject(TeamManagementService);

  repositories = signal<TeamRepository[]>([]);
  loading = signal(true);
  loadError = signal('');
  actionError = signal('');

  formOpen = signal(false);
  formEditing = signal<TeamRepository | null>(null);
  formUrl = signal('');
  formBranch = signal('main');
  formPaths = signal('');
  formLoading = signal(false);
  formError = signal('');

  deleteOpen = signal(false);
  deleteTarget = signal<TeamRepository | null>(null);
  deleteLoading = signal(false);
  deleteError = signal(false);

  credOpen = signal(false);
  credTarget = signal<TeamRepository | null>(null);
  credPem = signal('');
  credLoading = signal(false);
  credError = signal('');

  busyLinkId = signal<number | null>(null);

  readonly gridCols =
    'minmax(10rem, 1.4fr) minmax(5rem, 0.6fr) minmax(6rem, 0.7fr) minmax(7rem, 0.9fr) minmax(5rem, 0.7fr) minmax(8rem, auto)';

  ngOnChanges(): void {
    if (this.teamId) {
      void this.load();
    }
  }

  async load(): Promise<void> {
    this.loading.set(true);
    this.loadError.set('');
    try {
      this.repositories.set(await this.teamService.getTeamRepositories(this.teamId));
    } catch {
      this.loadError.set('Failed to load repositories, please refresh.');
      this.repositories.set([]);
    } finally {
      this.loading.set(false);
    }
  }

  openCreate(): void {
    this.formEditing.set(null);
    this.formUrl.set('');
    this.formBranch.set('main');
    this.formPaths.set('');
    this.formError.set('');
    this.formOpen.set(true);
  }

  openEdit(repo: TeamRepository): void {
    this.formEditing.set(repo);
    this.formUrl.set(repo.repo_url);
    this.formBranch.set(repo.branch || 'main');
    this.formPaths.set((repo.paths ?? []).join(', '));
    this.formError.set('');
    this.formOpen.set(true);
  }

  closeForm(): void {
    if (this.formLoading()) return;
    this.formOpen.set(false);
  }

  async submitForm(): Promise<void> {
    const url = this.formUrl().trim();
    if (!url || this.formLoading()) return;
    this.formLoading.set(true);
    this.formError.set('');
    this.actionError.set('');

    const paths = parsePaths(this.formPaths());
    const branch = this.formBranch().trim() || 'main';
    const editing = this.formEditing();

    try {
      if (editing) {
        await this.teamService.updateTeamRepository(this.teamId, editing.id, {
          repo_url: url,
          branch,
          paths: paths ?? [],
        });
      } else {
        await this.teamService.createTeamRepository(this.teamId, {
          repo_url: url,
          branch,
          paths,
        });
      }
      this.formOpen.set(false);
      await this.load();
    } catch (err: unknown) {
      this.formError.set(extractDetail(err) || 'Failed to save repository link, please try again.');
    } finally {
      this.formLoading.set(false);
    }
  }

  askDelete(repo: TeamRepository): void {
    this.deleteTarget.set(repo);
    this.deleteError.set(false);
    this.deleteOpen.set(true);
  }

  async confirmDelete(): Promise<void> {
    const target = this.deleteTarget();
    if (!target || this.deleteLoading()) return;
    this.deleteLoading.set(true);
    this.deleteError.set(false);
    this.actionError.set('');
    try {
      await this.teamService.deleteTeamRepository(this.teamId, target.id);
      this.deleteOpen.set(false);
      this.deleteTarget.set(null);
      await this.load();
    } catch {
      this.deleteError.set(true);
    } finally {
      this.deleteLoading.set(false);
    }
  }

  openCredentials(repo: TeamRepository): void {
    this.credTarget.set(repo);
    this.credPem.set('');
    this.credError.set('');
    this.credOpen.set(true);
  }

  closeCredentials(): void {
    if (this.credLoading()) return;
    this.credOpen.set(false);
  }

  async submitCredentials(): Promise<void> {
    const target = this.credTarget();
    const pem = this.credPem().trim();
    if (!target || !pem || this.credLoading()) return;
    this.credLoading.set(true);
    this.credError.set('');
    this.actionError.set('');
    try {
      await this.teamService.storeRepositoryCredentials(this.teamId, target.id, {
        private_key_pem: pem,
      });
      this.credOpen.set(false);
      await this.load();
    } catch (err: unknown) {
      this.credError.set(extractDetail(err) || 'Failed to store deploy key, please try again.');
    } finally {
      this.credLoading.set(false);
    }
  }

  async revokeCredentials(repo: TeamRepository): Promise<void> {
    if (this.busyLinkId() != null) return;
    this.busyLinkId.set(repo.id);
    this.actionError.set('');
    try {
      await this.teamService.revokeRepositoryCredentials(this.teamId, repo.id);
      await this.load();
    } catch (err: unknown) {
      this.actionError.set(extractDetail(err) || 'Failed to revoke credentials.');
    } finally {
      this.busyLinkId.set(null);
    }
  }

  async analyzeHeuristic(repo: TeamRepository): Promise<void> {
    if (this.busyLinkId() != null) return;
    this.busyLinkId.set(repo.id);
    this.actionError.set('');
    try {
      await this.teamService.analyzeRepositoryHeuristic(this.teamId, repo.id);
      await this.load();
    } catch (err: unknown) {
      this.actionError.set(extractDetail(err) || 'Heuristic analysis failed.');
    } finally {
      this.busyLinkId.set(null);
    }
  }

  async analyzeAgent(repo: TeamRepository): Promise<void> {
    if (this.busyLinkId() != null) return;
    this.busyLinkId.set(repo.id);
    this.actionError.set('');
    try {
      await this.teamService.analyzeRepositoryAgent(this.teamId, repo.id);
      await this.load();
    } catch (err: unknown) {
      this.actionError.set(extractDetail(err) || 'Failed to queue agent analysis.');
    } finally {
      this.busyLinkId.set(null);
    }
  }

  pathsLabel(repo: TeamRepository): string {
    if (!repo.paths || repo.paths.length === 0) return 'Entire repository';
    return repo.paths.join(', ');
  }

  analysisLabel(repo: TeamRepository): string {
    const a = repo.latest_analysis;
    if (!a) return 'None';
    const sha = a.commit_sha ? a.commit_sha.slice(0, 7) : '';
    return [a.status, a.source, sha].filter(Boolean).join(' · ');
  }
}

function parsePaths(raw: string): string[] | null {
  const parts = raw
    .split(/[,;\n]/)
    .map((p) => p.trim().replace(/^\/+|\/+$/g, ''))
    .filter(Boolean);
  return parts.length === 0 ? null : parts;
}

function extractDetail(err: unknown): string {
  const detail = (err as { error?: { detail?: string } } | null)?.error?.detail;
  return typeof detail === 'string' ? detail : '';
}
