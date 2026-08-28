import { ComponentFixture, TestBed } from '@angular/core/testing';

import { PasskeysService } from '../../core/services/passkeys.service';
import { getDeviceName } from '../../core/auth/passkey';
import { Passkey } from '../../shared/models/passkey.model';
import { Passkeys } from './passkeys';

/** Makes the real isPasskeySupported() report WebAuthn as available (or not). */
function stubPasskeySupport(supported: boolean): void {
  Object.defineProperty(window, 'isSecureContext', { value: supported, configurable: true });
  (window as unknown as Record<string, unknown>)['PublicKeyCredential'] =
    supported ? class {} : undefined;
  Object.defineProperty(window.navigator, 'credentials', {
    value: supported ? {} : undefined,
    configurable: true,
  });
}

describe('Passkeys', () => {
  let fixture: ComponentFixture<Passkeys>;
  let component: Passkeys;
  let service: {
    getPasskeys: ReturnType<typeof vi.fn>;
    registrationOptions: ReturnType<typeof vi.fn>;
    registerPasskey: ReturnType<typeof vi.fn>;
    deletePasskey: ReturnType<typeof vi.fn>;
  };

  const mac: Passkey = { id: 1, label: 'Mac - Chrome', credential_id: 'cred-1', created_at: '2026-01-02T10:00:00Z' };
  const phone: Passkey = { id: 2, label: null, credential_id: 'cred-2', created_at: '2026-02-03T11:00:00Z' };

  beforeEach(async () => {
    stubPasskeySupport(true);
    service = {
      getPasskeys: vi.fn().mockResolvedValue([mac, phone]),
      registrationOptions: vi.fn().mockResolvedValue({ challenge: 'c', rp: { name: 'Logos' }, user: { id: 'x' } }),
      registerPasskey: vi.fn(),
      deletePasskey: vi.fn().mockResolvedValue({ result: 'Passkey deleted' }),
    };

    await TestBed.configureTestingModule({
      imports: [Passkeys],
      providers: [{ provide: PasskeysService, useValue: service }],
    }).compileComponents();

    fixture = TestBed.createComponent(Passkeys);
    component = fixture.componentInstance;
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  });

  it('lists the passkeys of the current user', () => {
    expect(component.passkeys().map((p) => p.id)).toEqual([1, 2]);
    expect(fixture.nativeElement.textContent).toContain('Mac - Chrome');
  });

  it('falls back to a placeholder for unlabeled passkeys', () => {
    expect(fixture.nativeElement.textContent).toContain('Unnamed device');
  });

  describe('adding', () => {
    it('runs the ceremony with server-provided options and appends the passkey', async () => {
      const created: Passkey = { id: 3, label: 'Test - Chrome', credential_id: 'cred-3', created_at: '2026-03-04T12:00:00Z' };
      service.registerPasskey.mockResolvedValue(created);

      await component.addPasskey();

      expect(service.registrationOptions).toHaveBeenCalled();
      expect(service.registerPasskey).toHaveBeenCalledWith(expect.anything(), getDeviceName());
      expect(component.passkeys().map((p) => p.id)).toEqual([1, 2, 3]);
      expect(component.addError()).toBeNull();
    });

    it('treats a user cancellation as no error', async () => {
      service.registerPasskey.mockRejectedValue(new DOMException('cancelled', 'NotAllowedError'));

      await component.addPasskey();

      expect(component.addError()).toBeNull();
      expect(component.passkeys().map((p) => p.id)).toEqual([1, 2]);
    });

    it('shows the error message for a failed registration', async () => {
      service.registerPasskey.mockRejectedValue(new Error('Registration rejected by server'));

      await component.addPasskey();

      expect(component.addError()).toBe('Registration rejected by server');
      expect(component.passkeys().map((p) => p.id)).toEqual([1, 2]);
    });
  });

  describe('deleting', () => {
    it('removes the passkey after confirmation', async () => {
      component.requestDelete(mac);
      expect(component.deleteTarget()).toBe(mac);

      await component.confirmDelete();

      expect(service.deletePasskey).toHaveBeenCalledWith(1);
      expect(component.passkeys().map((p) => p.id)).toEqual([2]);
      expect(component.deleteTarget()).toBeNull();
    });

    it('keeps the passkey and reports an error when deletion fails', async () => {
      service.deletePasskey.mockRejectedValue(new Error('boom'));
      component.requestDelete(mac);

      await component.confirmDelete();

      expect(component.passkeys().map((p) => p.id)).toEqual([1, 2]);
      expect(component.deleteTarget()).toBe(mac);
      expect(component.deleteError()).toBe(true);
    });
  });

  it('hides the add button when the browser does not support passkeys', () => {
    stubPasskeySupport(false);
    const fresh = TestBed.createComponent(Passkeys);
    fresh.detectChanges();
    expect(fresh.componentInstance.supported()).toBe(false);
    expect(fresh.nativeElement.querySelector('.btn-primary')).toBeNull();
  });
});
