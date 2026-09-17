import { ComponentFixture, TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ModelManagementService } from '../../core/services/model-management.service';
import { ProviderManagementService } from '../../core/services/provider-management.service';
import { AddProviderPayload, Provider, UpdateProviderPayload } from '../../shared/models/provider.model';
import { Model } from '../../shared/models/model.model';
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

const makeModel = (id: number, name = `model-${id}`): Model => ({
  id,
  name,
  description: null,
  tags: null,
  aliases: null,
  weight_latency: null,
  weight_accuracy: null,
  weight_cost: null,
  weight_quality: null,
});

describe('Providers', () => {
  let fixture: ComponentFixture<Providers>;
  let component: Providers;
  let addProvider: ReturnType<typeof vi.fn>;
  let updateProvider: ReturnType<typeof vi.fn>;
  let refreshModels: ReturnType<typeof vi.fn>;
  let modelSyncStatus: ReturnType<typeof vi.fn>;
  let getModels: ReturnType<typeof vi.fn>;
  let getProviderModels: ReturnType<typeof vi.fn>;

  const optionValues = (options: { value: string }[]): string[] => options.map((o) => o.value);

  beforeEach(async () => {
    addProvider = vi.fn().mockResolvedValue({});
    updateProvider = vi.fn().mockResolvedValue({});
    refreshModels = vi.fn().mockResolvedValue({ result: 'Model refresh triggered.' });
    modelSyncStatus = vi.fn().mockResolvedValue({ running: false });
    getModels = vi.fn().mockResolvedValue([]);
    getProviderModels = vi.fn().mockResolvedValue([]);
    const providerService = {
      getProviders: vi.fn().mockResolvedValue([makeProvider()]),
      addProvider,
      updateProvider,
      refreshModels,
      modelSyncStatus,
      getProviderModels,
    };

    await TestBed.configureTestingModule({
      imports: [Providers],
      providers: [
        { provide: ProviderManagementService, useValue: providerService },
        { provide: ModelManagementService, useValue: { getModels } },
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

  describe('the model refresh', () => {
    beforeEach(() => {
      // The first change detection (and with it ngOnInit, which fetches the
      // model list) is otherwise scheduled outside the test's control and can
      // land inside the fake-timer window, skewing the call counts.
      fixture.detectChanges();
      getModels.mockClear();
    });

    it('triggers the backend sync and stops once the pass reports done', async () => {
      vi.useFakeTimers();
      try {
        const refresh = component.refreshModels();
        await vi.advanceTimersByTimeAsync(2000);
        await refresh;

        expect(refreshModels).toHaveBeenCalledTimes(1);
        // The pass reports idle on the first poll: one refetch, no rounds.
        expect(modelSyncStatus).toHaveBeenCalledTimes(1);
        expect(getModels).toHaveBeenCalledTimes(1);
        expect(component.refreshing()).toBe(false);
      } finally {
        vi.useRealTimers();
      }
    });

    it('keeps polling while the pass is still running', async () => {
      vi.useFakeTimers();
      try {
        modelSyncStatus
          .mockResolvedValueOnce({ running: true })
          .mockResolvedValueOnce({ running: true })
          .mockResolvedValueOnce({ running: false });
        getModels
          .mockResolvedValueOnce([])
          .mockResolvedValueOnce([makeModel(1)])
          .mockResolvedValueOnce([makeModel(1), makeModel(2)]);
        const refresh = component.refreshModels();
        await vi.advanceTimersByTimeAsync(2000 * 2);
        await refresh;

        expect(modelSyncStatus).toHaveBeenCalledTimes(3);
        expect(getModels).toHaveBeenCalledTimes(3);
        expect(component.allModels().map((m) => m.id)).toEqual([1, 2]);
      } finally {
        vi.useRealTimers();
      }
    });

    it('refetches the connections of an expanded provider', async () => {
      vi.useFakeTimers();
      try {
        component.toggleExpand(component.providers()[0]!);
        const refresh = component.refreshModels();
        await vi.advanceTimersByTimeAsync(2000);
        await refresh;

        // One from the expansion itself, one from the refresh refetch.
        expect(getProviderModels).toHaveBeenCalledTimes(2);
      } finally {
        vi.useRealTimers();
      }
    });

    it('does not start a second refresh while one is running', async () => {
      vi.useFakeTimers();
      try {
        const first = component.refreshModels();
        const second = component.refreshModels();
        await vi.advanceTimersByTimeAsync(2000 * 2);
        await Promise.all([first, second]);

        expect(refreshModels).toHaveBeenCalledTimes(1);
      } finally {
        vi.useRealTimers();
      }
    });

    it('surfaces an error when the trigger fails', async () => {
      refreshModels.mockRejectedValueOnce(new Error('orchestrator unreachable'));
      await component.refreshModels();

      expect(component.refreshError()).toBe(true);
      expect(component.refreshing()).toBe(false);
      expect(modelSyncStatus).not.toHaveBeenCalled();
      expect(getModels).not.toHaveBeenCalled();
    });

    it('retries an unreadable status within the rounds cap', async () => {
      vi.useFakeTimers();
      try {
        // A failed status read is unknown, not done: the accepted sync may
        // still be writing, so the UI polls until the cap instead of
        // reporting completion on a transient failure (timeout, rolling
        // deploy).
        modelSyncStatus.mockRejectedValue(new Error('unknown endpoint'));
        const refresh = component.refreshModels();
        await vi.advanceTimersByTimeAsync(45 * 2000 + 1000);
        await refresh;

        expect(modelSyncStatus).toHaveBeenCalledTimes(45);
        expect(getModels).toHaveBeenCalledTimes(45);
        expect(component.refreshing()).toBe(false);
        expect(component.refreshError()).toBe(false);
      } finally {
        vi.useRealTimers();
      }
    });

    it('keeps polling through unreadable statuses and stops on an explicit idle', async () => {
      vi.useFakeTimers();
      try {
        modelSyncStatus
          .mockRejectedValueOnce(new Error('timeout'))
          .mockResolvedValueOnce({ running: null })
          .mockResolvedValueOnce({ running: false });
        const refresh = component.refreshModels();
        await vi.advanceTimersByTimeAsync(2000 * 2);
        await refresh;

        expect(modelSyncStatus).toHaveBeenCalledTimes(3);
        expect(getModels).toHaveBeenCalledTimes(3);
        expect(component.refreshing()).toBe(false);
      } finally {
        vi.useRealTimers();
      }
    });

    it('gives up at the rounds cap if the pass never reports done', async () => {
      vi.useFakeTimers();
      try {
        modelSyncStatus.mockResolvedValue({ running: true });
        const refresh = component.refreshModels();
        // 45 rounds x 2 s is the component cap; the margin covers the
        // round work after the last timer.
        await vi.advanceTimersByTimeAsync(45 * 2000 + 1000);
        await refresh;

        expect(component.refreshing()).toBe(false);
        expect(component.refreshError()).toBe(false);
      } finally {
        vi.useRealTimers();
      }
    });
  });
});
