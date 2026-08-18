import {
  Component,
  computed,
  inject,
  signal,
  OnInit,
  ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { MyKeysService } from '../../core/services/my-keys.service';
import { MyKey, ModelAccess } from '../../shared/models/my-key.model';
import { SelectComponent, AppSelectOption } from '../../shared/components/select/select';

@Component({
  selector: 'app-open-code',
  standalone: true,
  imports: [CommonModule, SelectComponent],
  templateUrl: './open-code.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './open-code.scss',
})
export class OpenCode implements OnInit {
  private myKeysService = inject(MyKeysService);

  readonly String = String;

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
  connectMethod = signal<'download' | 'terminal'>('download');
  copiedCmd = signal<string | null>(null);

  maskedKey = computed(() => {
    const k = this.selectedKey()?.key_value ?? '';
    return k.length > 14 ? k.slice(0, 14) + ' ···' : k;
  });

  // /v1 is never routed on the admin entrypoint (:9443) this page is served on in
  // prod (docker-compose.yaml routes it to websecure/secure8080 instead), so that
  // port must be stripped. In dev, UI and /v1 share one port (docker-compose.dev.yaml,
  // web8080); there is no separate admin port there, so origin is left untouched.
  baseUrl = computed(() => window.location.origin.replace(/:9443$/, '') + '/v1');

  private buildConfig(withSchema: boolean): Record<string, unknown> {
    const key = this.selectedKey()?.key_value ?? '';
    const allModels = this.models();
    const defModel = this.selected();

    // Without an explicit limit opencode requests max_tokens: 32000 per completion.
    // Local models share a ~32k window between prompt and output, so every request
    // with a non-trivial prompt gets rejected with HTTP 400 (context overflow).
    // limit.output caps the requested max_tokens; limit.context tells opencode when
    // to compact the conversation. context_window is the window the workers really
    // serve (reported by the orchestrator); models without one get a conservative
    // fallback: 32768 for local models, a typical 128k window for cloud models.
    const modelsMap: Record<string, { name: string; limit: { context: number; output: number } }> =
      {};
    for (const m of allModels) {
      const local = m.provider_type !== 'cloud';
      const context = m.context_window && m.context_window > 0
        ? m.context_window
        : local
          ? 32768
          : 128000;
      modelsMap[m.model_name] = {
        name: m.model_name,
        limit: { context, output: Math.min(8192, Math.floor(context / 2)) },
      };
    }

    return {
      ...(withSchema ? { $schema: 'https://opencode.ai/config.json' } : {}),
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
  }

  configJson = computed(() => JSON.stringify(this.buildConfig(true), null, 2));

  configLines = computed(() => this.configJson().split('\n'));

  readonly keyOptions = computed<AppSelectOption[]>(() =>
    this.keys().map((k) => ({ value: String(k.id), label: k.name })),
  );

  readonly modelOptions = computed<AppSelectOption[]>(() =>
    this.models().map((m) => ({ value: m.model_name, label: m.model_name })),
  );

  readonly installCommands = {
    mac: 'brew install --cask opencode-desktop',
    macCli: 'brew install anomalyco/tap/opencode',
    linuxCli: 'curl -fsSL https://opencode.ai/install | bash',
    npmCli: 'npm install -g opencode-ai',
  } as const;

  // Merges only the Logos parts into an existing global config: provider.logos is
  // set/updated, an already configured default model is kept, everything else in
  // the file stays untouched. Creates file and directory if missing. Uses tools
  // the OS already has (python3 / PowerShell) so Node.js is not required.
  readonly mergeCommand = computed(() =>
    this.installTab() === 'windows' ? this.windowsMergeCommand() : this.posixMergeCommand(),
  );

  private posixMergeCommand(): string {
    // The JSON is passed as argv inside shell single quotes, so a literal ' in
    // the data (model names are admin-defined) must become '\''.
    const json = JSON.stringify(this.buildConfig(false)).replace(/'/g, "'\\''");
    return (
      "python3 -c 'import json,os,sys;" +
      'p=os.path.expanduser("~/.config/opencode/opencode.json");' +
      'add=json.loads(sys.argv[1]);' +
      'cfg=json.load(open(p)) if os.path.exists(p) else {};' +
      '"model" in add and cfg.setdefault("model",add["model"]);' +
      'cfg.setdefault("provider",{})["logos"]=add["provider"]["logos"];' +
      'os.makedirs(os.path.dirname(p),exist_ok=True);' +
      'json.dump(cfg,open(p,"w"),indent=2);' +
      'print("Logos provider written to "+p)\' ' +
      "'" + json + "'"
    );
  }

  private windowsMergeCommand(): string {
    // In a PowerShell single-quoted string a literal ' is escaped by doubling.
    const json = JSON.stringify(this.buildConfig(false)).replace(/'/g, "''");
    return (
      "$p=Join-Path $env:USERPROFILE '.config\\opencode\\opencode.json'; " +
      "$add='" + json + "' | ConvertFrom-Json; " +
      '$cfg=if(Test-Path $p){Get-Content $p -Raw | ConvertFrom-Json}else{[pscustomobject]@{}}; ' +
      'if($add.model -and !$cfg.model){$cfg | Add-Member model $add.model -Force}; ' +
      'if(!$cfg.provider){$cfg | Add-Member provider ([pscustomobject]@{})}; ' +
      '$cfg.provider | Add-Member logos $add.provider.logos -Force; ' +
      'New-Item -Force -ItemType Directory (Split-Path $p) | Out-Null; ' +
      '$cfg | ConvertTo-Json -Depth 12 | Set-Content $p; ' +
      'Write-Host "Logos provider written to $p"'
    );
  }

  async ngOnInit(): Promise<void> {
    try {
      const keys = await this.myKeysService.getMyKeys();
      this.keys.set(keys);
      this.keysLoading.set(false);
      // pickKey's own modelsLoading covers the (slower, orchestrator-dependent)
      // model fetch — keysLoading shouldn't stay true waiting on that too.
      if (keys.length > 0) await this.pickKey(keys[0]);
    } catch {
      this.keysError.set(true);
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
      // On duplicate names keep the local entry: buildConfig falls back to
      // provider_type-based limits, and the local window is the safe lower bound.
      const byName = new Map<string, ModelAccess>();
      for (const m of models) {
        const prev = byName.get(m.model_name);
        if (!prev || (prev.provider_type === 'cloud' && m.provider_type !== 'cloud')) {
          byName.set(m.model_name, m);
        }
      }
      const unique = [...byName.values()];
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
