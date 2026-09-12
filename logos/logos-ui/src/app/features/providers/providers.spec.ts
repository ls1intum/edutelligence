import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ModelManagementService } from '../../core/services/model-management.service';
import { ProviderManagementService } from '../../core/services/provider-management.service';
import { AddProviderPayload, Provider, UpdateProviderPayload } from '../../shared/models/provider.model';
import { Providers } from './providers';

/**
 * A cloud provider that is none of the named vendors — Hetzner, a vLLM
 * gateway — is configured by leaving the cloud type unset. That is the
 * configuration the generic machinery is built for: addressed at
 * /v1/chat/completions with a plain bearer token, and discovered over
 * GET /v1/models. The form used to make it unreachable: 'none' was filtered
 * out of the cloud list, the field defaulted to 'azure', and 'azure' is the
 * one type the /v1/models sync skips.
 */

const makeProvider = (overrides: Partial<Provider> = {}): Provider => ({
  id: 7,
  name: 'Hetzner',
  base_url: 'https://inference.hetzner.com/api/v1',
  api_key: 'hz-secret',
  auth_name: '',
  auth_format: '',
  provider_type: 'cloud',
  cloud_provider_type: null,
  privacy_level: 'CLOUD_IN_EU_BY_EU_PROVIDER',
  ...overrides,
});

describe('Providers', () => {
  let fixture: ComponentFixture<Providers>;
  let component: Providers;
  let addProvider: ReturnType<typeof vi.fn>;
  let updateProvider: ReturnType<typeof vi.fn>;

  const optionValues = (options: { value: string }[]): string[] => options.map((o) => o.value);

  beforeEach(async () => {
    addProvider = vi.fn().mockResolvedValue({});
    updateProvider = vi.fn().mockResolvedValue({});
    const providerService = {
      getProviders: vi.fn().mockResolvedValue([makeProvider()]),
      addProvider,
      updateProvider,
    };

    await TestBed.configureTestingModule({
      imports: [Providers],
      providers: [
        { provide: ProviderManagementService, useValue: providerService },
        { provide: ModelManagementService, useValue: { getModels: vi.fn().mockResolvedValue([]) } },
      ],
    }).compileComponents();
    fixture = TestBed.createComponent(Providers);
    component = fixture.componentInstance;
    await component.fetchProviders();
  });

  describe('the cloud provider type field', () => {
    it('offers an untyped option for a vendor that is not on the list', () => {
      component.onAddProviderTypeChange('cloud');
      expect(optionValues(component.addCloudProviderTypeOptions())).toContain('none');
    });

    it('does not default a new cloud provider to azure', async () => {
      // Azure has its own control-plane discovery and is excluded from the
      // /v1/models sync, so a provider saved on this default was scraped by
      // neither path and stayed empty.
      component.openAddDialog();
      component.addName.set('Hetzner');
      await component.submitAdd();

      const payload = addProvider.mock.calls[0][0] as AddProviderPayload;
      expect(payload.provider_type).toBe('cloud');
      expect(payload.cloud_provider_type).toBeUndefined();
    });

    it('keeps a named vendor the operator picked', async () => {
      component.openAddDialog();
      component.addName.set('OpenAI');
      component.addCloudProviderType.set('openai');
      await component.submitAdd();

      expect((addProvider.mock.calls[0][0] as AddProviderPayload).cloud_provider_type).toBe('openai');
    });

    it('does not relabel an untyped cloud provider as azure on edit', async () => {
      // Merely opening the dialog and saving used to move the provider onto
      // the Azure path, silently dropping it out of the sync it relied on.
      component.openEditDialog(makeProvider());
      expect(component.editCloudProviderType()).toBe('none');

      await component.submitEdit();
      expect((updateProvider.mock.calls[0][0] as UpdateProviderPayload).cloud_provider_type).toBe('none');
    });

    it('stays out of the way for a logosnode', () => {
      component.onAddProviderTypeChange('logosnode');
      expect(component.addProviderType()).toBe('logosnode');
      expect(component.addCloudProviderType()).toBe('none');
    });
  });

  describe('the provider type field', () => {
    it('opens on cloud for a new provider', () => {
      component.openAddDialog();
      expect(component.addProviderType()).toBe('cloud');
    });

    it('opens on the type the provider actually has', () => {
      component.openEditDialog(makeProvider({ provider_type: 'logosnode', privacy_level: 'LOCAL' }));
      expect(component.editProviderType()).toBe('logosnode');
    });

    it('renders the dialog on the bound type, not on the first option', async () => {
      // Regression for the app-select value binding: the dropdown read
      // "logosnode" while the component state said "cloud", so the operator
      // saw a provider type that was not the one being saved.
      component.openAddDialog();
      fixture.detectChanges();
      await fixture.whenStable();

      const selects = fixture.nativeElement.querySelectorAll('select') as NodeListOf<HTMLSelectElement>;
      const typeSelect = Array.from(selects).find((s) =>
        Array.from(s.options).some((o) => o.value === 'logosnode'),
      );
      expect(typeSelect?.value).toBe('cloud');
    });
  });
});
