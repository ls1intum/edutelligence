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
});
