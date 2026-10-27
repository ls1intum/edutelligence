import { ChangeDetectionStrategy, Component, OnInit, computed, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ModelRequest, ModelRequestService } from '../../core/services/model-request.service';
import { ModalConfirmComponent } from '../../shared/components/modal/modal-confirm/modal-confirm';
import { AuthService } from '../../core/auth/services/auth.service';

/**
 * The model-request voting section, embedded in the Models page.
 *
 * Ask for a model Logos does not serve yet by voting for it, and see the
 * running list of what everyone has voted for, most-voted first. Each user gets
 * one vote per model and can take it back — the Vote/Undo control on each row
 * reflects the caller's own vote state. Submitting is a demand signal, not a
 * configuration change: it records demand so operators can see what to add next.
 * Every request names one of the caller's teams (preselected to the first
 * one); the first team to ask for a model is recorded on it. A failed vote
 * (model already available, not found on Hugging Face, precheck timeout) is
 * surfaced in a modal; the typed name is kept so it can be corrected instead
 * of retyped.
 */
@Component({
  selector: 'app-model-requests',
  standalone: true,
  imports: [CommonModule, ModalConfirmComponent],
  templateUrl: './model-requests.html',
  styleUrl: './model-requests.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ModelRequests implements OnInit {
  private service = inject(ModelRequestService);
  private auth = inject(AuthService);

  requests = signal<ModelRequest[]>([]);
  loading = signal(false);
  submitting = signal(false);
  /** Load failure for the list, shown inline (load errors are not vote outcomes). */
  error = signal<string | null>(null);
  /** A failed vote, shown in a modal; null while no modal is open. */
  voteError = signal<string | null>(null);
  notice = signal<string | null>(null);
  name = signal('');
  showHelpImage = signal(false);
  /** The caller's teams — the only ones a request may name. */
  teams = computed(() => this.auth.currentUser()?.teams ?? []);
  /** The team the next request is for; null while none is (or can be) chosen. */
  teamId = signal<number | null>(null);

  async ngOnInit(): Promise<void> {
    // Preselect the first team: a member of exactly one team should not have
    // to make the choice; a member of several can still switch it.
    const first = this.teams()[0];
    if (first) this.teamId.set(first.id);
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
    if (!name || this.teamId() === null || this.submitting()) return;
    await this.castVote(name, this.teamId(), () => this.name.set(''));
  }

  /** Toggle the caller's vote on a listed model. */
  async toggle(request: ModelRequest): Promise<void> {
    if (this.submitting()) return;
    if (request.has_voted) {
      // Undoing a vote is the caller's own, so it needs no team.
      await this.castVote(request.name, null, null, { undo: true });
    } else if (this.teamId() !== null) {
      await this.castVote(request.name, this.teamId(), null);
    }
  }

  private async castVote(
    name: string,
    teamId: number | null,
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
      } else if (teamId === null) {
        // The Vote control is disabled without a selected team; backstop.
        return;
      } else {
        const updated = await this.service.vote(name, teamId);
        this.notice.set(
          `Thanks — "${updated.name}" now has ${updated.request_count} vote${
            updated.request_count === 1 ? '' : 's'
          }.`,
        );
      }
      onSuccess?.();
      await this.refresh();
    } catch (err: unknown) {
      // Vote outcomes are surfaced in a modal, not inline: the message needs
      // to be seen even though the user's attention is on the button.
      this.voteError.set(this.messageOf(err) ?? 'Something went wrong with the model request.');
    } finally {
      this.submitting.set(false);
    }
  }

  /** Close the failed-vote modal. */
  closeVoteError(): void {
    this.voteError.set(null);
  }

  /** Team selector change; the empty option clears the selection. */
  onTeamChange(value: string): void {
    this.teamId.set(value === '' ? null : Number(value));
  }

  private messageOf(err: unknown): string | null {
    const body = (err as { error?: { error?: string; detail?: string } })?.error;
    return body?.error ?? body?.detail ?? null;
  }
}