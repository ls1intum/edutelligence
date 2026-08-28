import { Component, OnInit, inject, signal, ChangeDetectionStrategy } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ModalConfirmComponent } from '../../shared/components/modal/modal-confirm/modal-confirm';
import { ErrorMessageComponent } from '../../shared/components/error-message/error-message';
import { IconTileComponent } from '../../shared/components/icon-tile/icon-tile';
import { PasskeysService } from '../../core/services/passkeys.service';
import { Passkey } from '../../shared/models/passkey.model';
import {
  isPasskeySupported,
  isPasskeyCancellation,
  passkeyErrorMessage,
  getDeviceName,
} from '../../core/auth/passkey';

@Component({
  selector: 'app-passkeys',
  standalone: true,
  imports: [CommonModule, ModalConfirmComponent, ErrorMessageComponent, IconTileComponent],
  templateUrl: './passkeys.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './passkeys.scss',
})
export class Passkeys implements OnInit {
  private passkeysService = inject(PasskeysService);

  passkeys = signal<Passkey[]>([]);
  supported = signal(false);
  loading = signal(true);
  loadError = signal(false);

  adding = signal(false);
  addError = signal<string | null>(null);

  deleteTarget = signal<Passkey | null>(null);
  deleteLoading = signal(false);
  deleteError = signal(false);

  async ngOnInit(): Promise<void> {
    this.supported.set(isPasskeySupported());
    await this.load();
  }

  async load(): Promise<void> {
    this.loading.set(true);
    this.loadError.set(false);
    try {
      this.passkeys.set(await this.passkeysService.getPasskeys());
    } catch {
      this.loadError.set(true);
    } finally {
      this.loading.set(false);
    }
  }

  async addPasskey(): Promise<void> {
    if (this.adding() || !this.supported()) return;
    this.adding.set(true);
    this.addError.set(null);
    try {
      const options = await this.passkeysService.registrationOptions();
      const passkey = await this.passkeysService.registerPasskey(options, getDeviceName());
      this.passkeys.update((list) => [...list, passkey]);
    } catch (error) {
      // The user may dismiss the platform prompt — that is not an error.
      if (!isPasskeyCancellation(error)) {
        this.addError.set(passkeyErrorMessage(error, 'Adding the passkey failed.'));
      }
    } finally {
      this.adding.set(false);
    }
  }

  requestDelete(passkey: Passkey): void {
    this.deleteError.set(false);
    this.deleteTarget.set(passkey);
  }

  closeDeleteModal(): void {
    if (this.deleteLoading()) return;
    this.deleteTarget.set(null);
  }

  async confirmDelete(): Promise<void> {
    const target = this.deleteTarget();
    if (!target || this.deleteLoading()) return;
    this.deleteLoading.set(true);
    this.deleteError.set(false);
    try {
      await this.passkeysService.deletePasskey(target.id);
      this.passkeys.update((list) => list.filter((p) => p.id !== target.id));
      this.deleteTarget.set(null);
    } catch {
      this.deleteError.set(true);
    } finally {
      this.deleteLoading.set(false);
    }
  }

  formatCreatedAt(iso: string): string {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString();
  }
}
