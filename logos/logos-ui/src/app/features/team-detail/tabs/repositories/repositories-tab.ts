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
 * Links GitHub repositories to the team so a later LogosOSSAgent pass can
 * analyse AI workflows and recommend SLAs. This tab is only the link book:
 * public URL, branch, optional path filters — no credentials and no analysis
 * results yet.
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

  readonly gridCols = 'minmax(10rem, 1.4fr) minmax(6rem, 0.7fr) minmax(8rem, 1fr) minmax(5rem, auto)';

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
          // Empty must be [] so the service clears stored filters; null means
          // "leave paths alone" on the PATCH contract.
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

  pathsLabel(repo: TeamRepository): string {
    if (!repo.paths || repo.paths.length === 0) return 'Entire repository';
    return repo.paths.join(', ');
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
