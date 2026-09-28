import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ModelRequest, ModelRequestService } from '../../core/services/model-request.service';

/**
 * The model-request voting section, embedded in the Models page.
 *
 * Ask for a model Logos does not serve yet by voting for it, and see the
 * running list of what everyone has voted for, most-voted first. Each user gets
 * one vote per model and can take it back — the Vote/Undo control on each row
 * reflects the caller's own vote state. Submitting is a demand signal, not a
 * configuration change: it records demand so operators can see what to add next.
 */
@Component({
  selector: 'app-model-requests',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './model-requests.html',
  styleUrl: './model-requests.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ModelRequests implements OnInit {
  private service = inject(ModelRequestService);

  requests = signal<ModelRequest[]>([]);
  loading = signal(false);
  submitting = signal(false);
  error = signal<string | null>(null);
  notice = signal<string | null>(null);
  name = signal('');

  async ngOnInit(): Promise<void> {
    await this.refresh();
  }

  async refresh(): Promise<void> {
    this.loading.set(true);
    try {
      this.requests.set(await this.service.list());
    } catch {
      this.error.set('Could not load model requests.');
    } finally {
      this.loading.set(false);
    }
  }

  /** Vote for a model typed into the form (a new request). */
  async submit(): Promise<void> {
    const name = this.name().trim();
    if (!name || this.submitting()) return;
    await this.castVote(name, () => this.name.set(''));
  }

  /** Toggle the caller's vote on a listed model. */
  async toggle(request: ModelRequest): Promise<void> {
    if (this.submitting()) return;
    if (request.has_voted) {
      await this.castVote(request.name, null, { undo: true });
    } else {
      await this.castVote(request.name, null);
    }
  }

  private async castVote(
    name: string,
    onSuccess: (() => void) | null,
    opts: { undo?: boolean } = {},
  ): Promise<void> {
    this.submitting.set(true);
    this.error.set(null);
    this.notice.set(null);
    try {
      if (opts.undo) {
        await this.service.undoVote(name);
        this.notice.set(`Vote removed for "${name}".`);
      } else {
        const updated = await this.service.vote(name);
        this.notice.set(
          `Thanks — "${updated.name}" now has ${updated.request_count} vote${
            updated.request_count === 1 ? '' : 's'
          }.`,
        );
      }
      onSuccess?.();
      await this.refresh();
    } catch (err: unknown) {
      this.error.set(this.messageOf(err) ?? 'Something went wrong with the model request.');
    } finally {
      this.submitting.set(false);
    }
  }

  private messageOf(err: unknown): string | null {
    const body = (err as { error?: { error?: string; detail?: string } })?.error;
    return body?.error ?? body?.detail ?? null;
  }
}
