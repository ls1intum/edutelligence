import { SimpleChange } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { TeamManagementService } from '../../../core/services/team-management.service';
import { TeamApiKey } from '../../../shared/models/team.model';
import { ApiKeyModalComponent } from './api-key-modal';

describe('ApiKeyModalComponent', () => {
  let fixture: ComponentFixture<ApiKeyModalComponent>;
  let component: ApiKeyModalComponent;
  let teamService: {
    updateApiKey: ReturnType<typeof vi.fn>;
    setApiKeyProviderPermissions: ReturnType<typeof vi.fn>;
    setApiKeyModelPermissions: ReturnType<typeof vi.fn>;
    rotateApiKey: ReturnType<typeof vi.fn>;
  };

  const key: TeamApiKey = {
    id: 42,
    name: 'developer-key',
    key_type: 'developer',
    monthly_budget_micro_cents: null,
    cloud_rpm_limit: null,
    cloud_tpm_limit: null,
    local_rpm_limit: null,
    local_tpm_limit: null,
  };

  beforeEach(async () => {
    teamService = {
      updateApiKey: vi.fn().mockResolvedValue(undefined),
      setApiKeyProviderPermissions: vi.fn().mockResolvedValue(undefined),
      setApiKeyModelPermissions: vi.fn().mockResolvedValue(undefined),
      rotateApiKey: vi.fn().mockResolvedValue({ result: 'ok', api_key: 'lg-rotated-123' }),
    };

    await TestBed.configureTestingModule({
      imports: [ApiKeyModalComponent],
      providers: [{ provide: TeamManagementService, useValue: teamService }],
    }).compileComponents();

    fixture = TestBed.createComponent(ApiKeyModalComponent);
    component = fixture.componentInstance;
    component.visible = true;
    component.key = key;
    component.canEdit = true;
    fixture.detectChanges();
  });

  it('allows an editor to enable custom permissions', () => {
    const toggle: HTMLButtonElement = fixture.nativeElement.querySelector('.toggle-btn');

    expect(toggle.disabled).toBe(false);
    toggle.click();

    expect(component.fCustom()).toBe(true);
  });

  it('updates provider and model permissions when saving an override', async () => {
    component.fCustom.set(true);
    component.selectedProviderIds.set(new Set([10]));
    component.selectedModelIds.set(new Set([20]));

    await component.save();

    expect(teamService.setApiKeyProviderPermissions).toHaveBeenCalledWith(42, [10]);
    expect(teamService.setApiKeyModelPermissions).toHaveBeenCalledWith(42, [20]);
  });

  describe('rotation', () => {
    it('updates the shared key object after a successful rotation', async () => {
      key.key_value = 'lg-old-key-42';

      await component.confirmRotate();

      expect(teamService.rotateApiKey).toHaveBeenCalledWith(42);
      expect(key.key_value).toBe('lg-rotated-123');
      expect(component.effectiveKeyValue()).toBe('lg-rotated-123');
      expect(component.rotateConfirm()).toBe(false);
      expect(component.rotateError()).toBe('');
    });

    it('shows the rotated key when the modal is closed and reopened', async () => {
      key.key_value = 'lg-old-key-42';

      await component.confirmRotate();

      // Reopening the modal re-runs initForm via ngOnChanges, resetting the
      // transient form state; the displayed value must come from the (now
      // rotated) key object, not a stale pre-rotation value (issue #733).
      component.ngOnChanges({
        visible: new SimpleChange(false, true, false),
        key: new SimpleChange(null, key, false),
      });

      expect(component.effectiveKeyValue()).toBe('lg-rotated-123');
      expect(component.maskedKey()).toContain('lg-rotated-123');
    });

    it('keeps the old key and reports an error when rotation fails', async () => {
      teamService.rotateApiKey.mockRejectedValue(new Error('boom'));
      key.key_value = 'lg-old-key-42';
      component.requestRotate();

      await component.confirmRotate();

      expect(key.key_value).toBe('lg-old-key-42');
      expect(component.effectiveKeyValue()).toBe('lg-old-key-42');
      expect(component.rotateError()).toBe('Failed to rotate key, please try again.');
      // The confirm box stays open so the user can retry or cancel.
      expect(component.rotateConfirm()).toBe(true);
    });
  });
});
