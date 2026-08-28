import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { Passkey } from '../../shared/models/passkey.model';
import { createPasskeyCredential, PasskeyCreationOptions } from '../auth/passkey';

/**
 * User passkey management against the webservice (#694): list, add multiple,
 * delete. The add flow runs the WebAuthn ceremony in the browser
 * (createPasskeyCredential) and then stores the verified credential server-side.
 */
@Injectable({ providedIn: 'root' })
export class PasskeysService {
  private http = inject(HttpClient);

  getPasskeys(): Promise<Passkey[]> {
    return firstValueFrom(this.http.get<Passkey[]>('/api/me/passkeys'));
  }

  registrationOptions(): Promise<PasskeyCreationOptions> {
    return firstValueFrom(this.http.post<PasskeyCreationOptions>('/api/me/passkeys/options', {}));
  }

  /** Runs the ceremony, then registers the returned credential. */
  registerPasskey(options: PasskeyCreationOptions, label: string): Promise<Passkey> {
    return createPasskeyCredential(options).then((response) =>
      firstValueFrom(
        this.http.post<{ result: string; passkey: Passkey }>('/api/me/passkeys', {
          ...response,
          challenge: options.challenge,
          label,
        }),
      ),
    ).then((res) => res.passkey);
  }

  deletePasskey(id: number): Promise<{ result: string }> {
    return firstValueFrom(this.http.delete<{ result: string }>(`/api/me/passkeys/${id}`));
  }
}
