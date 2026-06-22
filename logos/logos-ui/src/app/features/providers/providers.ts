import { Component, computed, inject, signal, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ModalFormComponent } from '../../shared/components/modal/modal-form/modal-form';
import { ModalConfirmComponent } from '../../shared/components/modal/modal-confirm/modal-confirm';
import { ProviderManagementService } from '../../core/services/provider-management.service';
import { ModelManagementService } from '../../core/services/model-management.service';
import {
  Provider, ModelConnection, AddProviderPayload, UpdateProviderPayload,
  ProviderType, CloudProviderType, PrivacyLevel,
} from '../../shared/models/provider.model';
import { Model } from '../../shared/models/model.model';
import { SearchInputComponent } from '../../shared/components/search-input/search-input';
import { DataTableComponent } from '../../shared/components/data-table/data-table';
import { ErrorMessageComponent } from '../../shared/components/error-message/error-message';

@Component({
  selector: 'app-providers',
  standalone: true,
  imports: [FormsModule, ModalFormComponent, ModalConfirmComponent, SearchInputComponent, DataTableComponent, ErrorMessageComponent],
  templateUrl: './providers.html',
  styleUrl: './providers.scss',
})
export class Providers implements OnInit {
  private providerService = inject(ProviderManagementService);
  private modelService    = inject(ModelManagementService);

  readonly providerTypes: ProviderType[]           = ['logosnode', 'cloud'];
  readonly cloudProviderTypes: CloudProviderType[] = ['azure', 'openai', 'anthropic', 'gemini', 'bedrock', 'deepseek', 'groq', 'none'];
  readonly privacyLevels: PrivacyLevel[]           = ['LOCAL', 'CLOUD_IN_EU_BY_US_PROVIDER', 'CLOUD_NOT_IN_EU_BY_US_PROVIDER', 'CLOUD_IN_EU_BY_EU_PROVIDER'];

  // ── List state ──────────────────────────────────────────────────────────
  providers  = signal<Provider[]>([]);
  loading    = signal(true);
  search     = signal('');
  loadError  = signal(false);

  // ── Expand state ─────────────────────────────────────────────────────────
  expandedId     = signal<number | null>(null);
  providerModels = signal<Record<number, ModelConnection[]>>({});

  // ── All models (for connect picker) ──────────────────────────────────────
  allModels = signal<Model[]>([]);

  // ── Delete modal ────────────────────────────────────────────────────────
  deleteTarget  = signal<Provider | null>(null);
  deleteLoading = signal(false);
  deleteError   = signal(false);

  // ── Add modal ────────────────────────────────────────────────────────────
  addOpen              = signal(false);
  addName              = signal('');
  addBaseUrl           = signal('');
  addApiKey            = signal('');
  addAuthName          = signal('');
  addAuthFormat        = signal('');
  addProviderType      = signal<ProviderType>('cloud');
  addCloudProviderType = signal<CloudProviderType>('none');
  addPrivacyLevel      = signal<PrivacyLevel>('LOCAL');
  addLoading           = signal(false);
  addError             = signal('');

  // ── Edit modal ────────────────────────────────────────────────────────────
  editTarget           = signal<Provider | null>(null);
  editName             = signal('');
  editBaseUrl          = signal('');
  editApiKey           = signal('');
  editAuthName         = signal('');
  editAuthFormat       = signal('');
  editProviderType     = signal<ProviderType>('cloud');
  editCloudProviderType = signal<CloudProviderType>('none');
  editPrivacyLevel     = signal<PrivacyLevel>('LOCAL');
  editLoading          = signal(false);
  editError            = signal('');

  // ── Connect model modal ───────────────────────────────────────────────────
  connectTarget   = signal<Provider | null>(null);
  connectModelId  = signal<number | null>(null);
  connectEndpoint = signal('');
  connectApiKey   = signal('');
  connectLoading  = signal(false);
  connectError    = signal('');

  // ── Edit connection modal ─────────────────────────────────────────────────
  editConnProvider = signal<Provider | null>(null);
  editConnModel    = signal<ModelConnection | null>(null);
  editConnEndpoint = signal('');
  editConnApiKey   = signal('');
  editConnLoading  = signal(false);
  editConnError    = signal('');

  // ── Disconnect model modal ────────────────────────────────────────────────
  disconnectProvider = signal<Provider | null>(null);
  disconnectTarget   = signal<ModelConnection | null>(null);
  disconnectLoading  = signal(false);
  disconnectError    = signal(false);

  // ── Computed ─────────────────────────────────────────────────────────────
  filteredProviders = computed(() => {
    const q = this.search().toLowerCase().trim();
    if (!q) return this.providers();
    return this.providers().filter(p =>
      p.name.toLowerCase().includes(q) ||
      p.base_url.toLowerCase().includes(q)
    );
  });

  addValid     = computed(() => this.addName().trim().length > 0 && this.addBaseUrl().trim().length > 0);
  connectValid = computed(() => this.connectModelId() !== null);

  connectableModels = computed(() => {
    const target = this.connectTarget();
    if (!target) return this.allModels();
    const connected = new Set((this.providerModels()[target.id] ?? []).map(c => c.model_id));
    return this.allModels().filter(m => !connected.has(m.id));
  });

  ngOnInit(): void {
    this.fetchProviders();
    this.modelService.getModels().subscribe({
      next: models => this.allModels.set(models),
      error: () => {},
    });
  }

  fetchProviders(): void {
    this.loading.set(true);
    this.loadError.set(false);
    this.providerService.getProviders().subscribe({
      next: p => { this.providers.set(p); this.loading.set(false); },
      error: () => { this.loadError.set(true); this.loading.set(false); },
    });
  }

  formatPrivacy(level: PrivacyLevel): string {
    const map: Record<PrivacyLevel, string> = {
      LOCAL: 'LOCAL',
      CLOUD_IN_EU_BY_US_PROVIDER:     'EU (US)',
      CLOUD_NOT_IN_EU_BY_US_PROVIDER: 'Non-EU (US)',
      CLOUD_IN_EU_BY_EU_PROVIDER:     'EU (EU)',
    };
    return map[level] ?? level;
  }

  // ── Expand ────────────────────────────────────────────────────────────────
  toggleExpand(provider: Provider): void {
    if (this.expandedId() === provider.id) {
      this.expandedId.set(null);
      return;
    }
    this.expandedId.set(provider.id);
    if (!this.providerModels()[provider.id]) {
      this.loadProviderModels(provider.id);
    }
  }

  loadProviderModels(providerId: number): void {
    this.providerService.getProviderModels(providerId).subscribe({
      next: conns => this.providerModels.update(m => ({ ...m, [providerId]: conns })),
      error: () => this.providerModels.update(m => ({ ...m, [providerId]: [] })),
    });
  }

  // ── Delete flow ───────────────────────────────────────────────────────────
  openDeleteDialog(provider: Provider): void {
    this.deleteTarget.set(provider);
    this.deleteError.set(false);
  }

  closeDeleteDialog(): void {
    if (this.deleteLoading()) return;
    this.deleteTarget.set(null);
  }

  confirmDelete(): void {
    const target = this.deleteTarget();
    if (!target || this.deleteLoading()) return;
    this.deleteLoading.set(true);
    this.deleteError.set(false);
    this.providerService.deleteProvider(target.id).subscribe({
      next: () => {
        this.providers.update(list => list.filter(p => p.id !== target.id));
        this.deleteLoading.set(false);
        this.deleteTarget.set(null);
      },
      error: () => {
        this.deleteLoading.set(false);
        this.deleteError.set(true);
      },
    });
  }

  // ── Add flow ──────────────────────────────────────────────────────────────
  openAddDialog(): void {
    this.addName.set(''); this.addBaseUrl.set(''); this.addApiKey.set('');
    this.addAuthName.set(''); this.addAuthFormat.set('');
    this.addProviderType.set('cloud'); this.addCloudProviderType.set('none');
    this.addPrivacyLevel.set('LOCAL'); this.addError.set('');
    this.addOpen.set(true);
  }

  closeAddDialog(): void {
    if (this.addLoading()) return;
    this.addOpen.set(false);
  }

  submitAdd(): void {
    if (!this.addValid() || this.addLoading()) return;
    this.addLoading.set(true);
    this.addError.set('');
    const payload: AddProviderPayload = {
      name: this.addName().trim(),
      base_url: this.addBaseUrl().trim(),
      api_key: this.addApiKey().trim() || undefined,
      auth_name: this.addAuthName().trim() || undefined,
      auth_format: this.addAuthFormat().trim() || undefined,
      provider_type: this.addProviderType(),
      cloud_provider_type: this.addCloudProviderType() === 'none' ? undefined : this.addCloudProviderType(),
      privacy_level: this.addPrivacyLevel(),
    };
    this.providerService.addProvider(payload).subscribe({
      next: () => {
        this.fetchProviders();
        this.addLoading.set(false);
        this.addOpen.set(false);
      },
      error: () => {
        this.addLoading.set(false);
        this.addError.set('Failed to add provider, please try again.');
      },
    });
  }

  // ── Edit flow ─────────────────────────────────────────────────────────────
  openEditDialog(provider: Provider): void {
    this.editTarget.set(provider);
    this.editName.set(provider.name);
    this.editBaseUrl.set(provider.base_url);
    this.editApiKey.set(provider.api_key ?? '');
    this.editAuthName.set(provider.auth_name ?? '');
    this.editAuthFormat.set(provider.auth_format ?? '');
    this.editProviderType.set(provider.provider_type);
    this.editCloudProviderType.set(provider.cloud_provider_type ?? 'none');
    this.editPrivacyLevel.set(provider.privacy_level);
    this.editError.set('');
  }

  closeEditDialog(): void {
    if (this.editLoading()) return;
    this.editTarget.set(null);
  }

  submitEdit(): void {
    const target = this.editTarget();
    if (!target || this.editLoading()) return;
    this.editLoading.set(true);
    this.editError.set('');
    const payload: UpdateProviderPayload = {
      provider_id: target.id,
      name: this.editName().trim() || undefined,
      base_url: this.editBaseUrl().trim() || undefined,
      api_key: this.editApiKey().trim() || undefined,
      auth_name: this.editAuthName().trim() || undefined,
      auth_format: this.editAuthFormat().trim() || undefined,
      provider_type: this.editProviderType(),
      cloud_provider_type: this.editCloudProviderType() === 'none' ? null : this.editCloudProviderType(),
      privacy_level: this.editPrivacyLevel(),
    };
    this.providerService.updateProvider(payload).subscribe({
      next: () => {
        this.fetchProviders();
        this.editLoading.set(false);
        this.editTarget.set(null);
      },
      error: () => {
        this.editLoading.set(false);
        this.editError.set('Failed to save changes, please try again.');
      },
    });
  }

  // ── Connect model flow ────────────────────────────────────────────────────
  openConnectDialog(provider: Provider): void {
    this.connectTarget.set(provider);
    this.connectModelId.set(null);
    this.connectEndpoint.set('');
    this.connectApiKey.set('');
    this.connectError.set('');
  }

  closeConnectDialog(): void {
    if (this.connectLoading()) return;
    this.connectTarget.set(null);
  }

  submitConnect(): void {
    const target  = this.connectTarget();
    const modelId = this.connectModelId();
    if (!target || modelId === null || this.connectLoading()) return;
    this.connectLoading.set(true);
    this.connectError.set('');
    this.providerService.connectModel(
      target.id, modelId,
      this.connectEndpoint().trim() || undefined,
      this.connectApiKey().trim() || undefined,
    ).subscribe({
      next: () => {
        this.loadProviderModels(target.id);
        this.connectLoading.set(false);
        this.connectTarget.set(null);
      },
      error: () => {
        this.connectLoading.set(false);
        this.connectError.set('Failed to connect model, please try again.');
      },
    });
  }

  // ── Edit connection flow ──────────────────────────────────────────────────
  openEditConnDialog(provider: Provider, conn: ModelConnection): void {
    this.editConnProvider.set(provider);
    this.editConnModel.set(conn);
    this.editConnEndpoint.set(conn.endpoint ?? '');
    this.editConnApiKey.set(conn.api_key ?? '');
    this.editConnError.set('');
  }

  closeEditConnDialog(): void {
    if (this.editConnLoading()) return;
    this.editConnProvider.set(null);
    this.editConnModel.set(null);
  }

  submitEditConn(): void {
    const provider = this.editConnProvider();
    const conn     = this.editConnModel();
    if (!provider || !conn || this.editConnLoading()) return;
    this.editConnLoading.set(true);
    this.editConnError.set('');
    this.providerService.connectModel(
      provider.id, conn.model_id,
      this.editConnEndpoint().trim() || undefined,
      this.editConnApiKey().trim() || undefined,
    ).subscribe({
      next: () => {
        this.loadProviderModels(provider.id);
        this.editConnLoading.set(false);
        this.editConnProvider.set(null);
        this.editConnModel.set(null);
      },
      error: () => {
        this.editConnLoading.set(false);
        this.editConnError.set('Failed to save, please try again.');
      },
    });
  }

  openDisconnectDialog(provider: Provider, conn: ModelConnection): void {
    this.disconnectProvider.set(provider);
    this.disconnectTarget.set(conn);
    this.disconnectError.set(false);
  }

  closeDisconnectDialog(): void {
    if (this.disconnectLoading()) return;
    this.disconnectProvider.set(null);
    this.disconnectTarget.set(null);
  }

  confirmDisconnect(): void {
    const provider = this.disconnectProvider();
    const conn     = this.disconnectTarget();
    if (!provider || !conn || this.disconnectLoading()) return;
    this.disconnectLoading.set(true);
    this.disconnectError.set(false);
    this.providerService.disconnectModel(provider.id, conn.model_id).subscribe({
      next: () => {
        this.providerModels.update(m => ({
          ...m,
          [provider.id]: (m[provider.id] ?? []).filter(c => c.model_id !== conn.model_id),
        }));
        this.disconnectLoading.set(false);
        this.disconnectProvider.set(null);
        this.disconnectTarget.set(null);
      },
      error: () => {
        this.disconnectLoading.set(false);
        this.disconnectError.set(true);
      },
    });
  }
}
