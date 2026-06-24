import {
  Component,
  computed,
  inject,
  signal,
  OnInit,
  ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { AuthService } from '../../core/auth/services/auth.service';
import { MyKeysService } from '../my-keys/my-keys.service';
import { MyKey, ModelAccess } from '../../shared/models/my-key.model';

@Component({
  selector: 'app-open-code',
  standalone: true,
  imports: [CommonModule],
  templateUrl: './open-code.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './open-code.scss',
})
export class OpenCode implements OnInit {
  auth = inject(AuthService);
  private myKeysService = inject(MyKeysService);

  // ── Key list ──────────────────────────────────────────────────────────────
  keys = signal<MyKey[]>([]);
  keysLoading = signal(true);
  keysError = signal(false);
  selectedKey = signal<MyKey | null>(null);

  // ── Models for selected key ───────────────────────────────────────────────
  models = signal<ModelAccess[]>([]);
  modelsLoading = signal(false);
  modelsError = signal(false);
  selected = signal<ModelAccess | null>(null);

  // ── UI state ──────────────────────────────────────────────────────────────
  installTab = signal<'mac' | 'linux' | 'windows'>('mac');
  applyTab = signal<'mac' | 'windows'>('mac');
  copiedCmd = signal<string | null>(null);

  maskedKey = computed(() => {
    const k = this.selectedKey()?.key_value ?? '';
    return k.length > 14 ? k.slice(0, 14) + ' ···' : k;
  });

  baseUrl = computed(() => `${window.location.origin}/v1`);

  configJson = computed(() => {
    const key = this.selectedKey()?.key_value ?? '';
    const allModels = this.models();
    const defModel = this.selected();

    const modelsMap: Record<string, { name: string }> = {};
    for (const m of allModels) {
      modelsMap[m.model_name] = { name: m.model_name };
    }

    const cfg: Record<string, unknown> = {
      $schema: 'https://opencode.ai/config.json',
      ...(defModel ? { model: `logos/${defModel.model_name}` } : {}),
      provider: {
        logos: {
          npm: '@ai-sdk/openai-compatible',
          name: 'Logos LLM Platform',
          options: {
            baseURL: this.baseUrl(),
            apiKey: key,
          },
          ...(allModels.length > 0 ? { models: modelsMap } : {}),
        },
      },
    };
    return JSON.stringify(cfg, null, 2);
  });

  configLines = computed(() => this.configJson().split('\n'));

  readonly installCommands = {
    mac: 'brew install sst/tap/opencode',
    linux: 'npm install -g opencode@latest',
    windows: 'winget install SST.OpenCode',
  } as const;

  readonly applyCommands = {
    mac: 'cp opencode.json ~/.config/opencode/opencode.json',
    windows: 'Copy-Item opencode.json "$env:APPDATA\\opencode\\opencode.json"',
  } as const;

  async ngOnInit(): Promise<void> {
    try {
      const keys = await this.myKeysService.getMyKeys();
      this.keys.set(keys);
      const sessionKey = keys.find((k) => k.key_value === this.auth.apiKey()) ?? keys[0] ?? null;
      if (sessionKey) await this.pickKey(sessionKey);
    } catch {
      this.keysError.set(true);
    } finally {
      this.keysLoading.set(false);
    }
  }

  selectKeyById(id: string) {
    const key = this.keys().find((k) => k.id === Number(id)) ?? null;
    if (key) this.pickKey(key);
  }

  private async pickKey(key: MyKey): Promise<void> {
    this.selectedKey.set(key);
    this.models.set([]);
    this.selected.set(null);
    this.modelsLoading.set(true);
    this.modelsError.set(false);
    try {
      const models = await this.myKeysService.getKeyModels(key.id);
      const unique = [...new Map(models.map((m) => [m.model_name, m])).values()];
      this.models.set(unique);
      if (unique.length > 0) this.selected.set(unique[0]);
    } catch {
      this.modelsError.set(true);
    } finally {
      this.modelsLoading.set(false);
    }
  }

  selectModel(name: string) {
    this.selected.set(this.models().find((m) => m.model_name === name) ?? null);
  }

  downloadConfig() {
    const blob = new Blob([this.configJson()], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'opencode.json';
    a.click();
    URL.revokeObjectURL(url);
  }

  copyCmd(text: string) {
    navigator.clipboard.writeText(text).then(() => {
      this.copiedCmd.set(text);
      setTimeout(() => this.copiedCmd.set(null), 2000);
    });
  }
}
