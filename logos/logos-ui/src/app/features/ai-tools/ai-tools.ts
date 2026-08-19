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
  selector: 'app-ai-tools',
  standalone: true,
  imports: [CommonModule, SelectComponent],
  templateUrl: './ai-tools.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './ai-tools.scss',
})
export class AiTools implements OnInit {
  private myKeysService = inject(MyKeysService);

  readonly String = String;

  // ── Tool tab ──────────────────────────────────────────────────────────────
  activeTool = signal<'opencode' | 'claudecode'>('opencode');

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

  // ── Shared computed ───────────────────────────────────────────────────────
  maskedKey = computed(() => {
    const k = this.selectedKey()?.key_value ?? '';
    return k.length > 14 ? k.slice(0, 14) + ' ···' : k;
  });

  // /v1 is never routed on the admin entrypoint (:9443) this page is served on in
  // prod; that port is stripped. In dev, UI and /v1 share one port, so origin is
  // left untouched.
  baseUrlV1 = computed(() => window.location.origin.replace(/:9443$/, '') + '/v1');

  // Claude Code appends /v1/messages itself, so it must NOT carry the /v1 suffix.
  baseUrl = computed(() => window.location.origin.replace(/:9443$/, ''));

  // ── Key options: show team name only ─────────────────────────────────────
  readonly keyOptions = computed<AppSelectOption[]>(() =>
    this.keys().map((k) => ({ value: String(k.id), label: k.team.name })),
  );

  readonly modelOptions = computed<AppSelectOption[]>(() =>
    this.models().map((m) => ({ value: m.model_name, label: m.model_name })),
  );

  // ── OpenCode ──────────────────────────────────────────────────────────────
  private buildOpenCodeConfig(withSchema: boolean): Record<string, unknown> {
    const key = this.selectedKey()?.key_value ?? '';
    const allModels = this.models();
    const defModel = this.selected();

    const modelsMap: Record<string, { name: string; limit: { context: number; output: number } }> =
      {};
    for (const m of allModels) {
      const local = m.provider_type !== 'cloud';
      const context =
        m.context_window && m.context_window > 0
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
            baseURL: this.baseUrlV1(),
            apiKey: key,
          },
          ...(allModels.length > 0 ? { models: modelsMap } : {}),
        },
      },
    };
  }

  openCodeConfigJson = computed(() => JSON.stringify(this.buildOpenCodeConfig(true), null, 2));
  openCodeConfigLines = computed(() => this.openCodeConfigJson().split('\n'));

  readonly openCodeInstallCommands = {
    mac: 'brew install --cask opencode-desktop',
    macCli: 'brew install anomalyco/tap/opencode',
    linuxCli: 'curl -fsSL https://opencode.ai/install | bash',
    npmCli: 'npm install -g opencode-ai',
  } as const;

  readonly openCodeMergeCommand = computed(() =>
    this.installTab() === 'windows'
      ? this.openCodeWindowsMergeCommand()
      : this.openCodePosixMergeCommand(),
  );

  private openCodePosixMergeCommand(): string {
    const json = JSON.stringify(this.buildOpenCodeConfig(false)).replace(/'/g, "'\\''");
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
      "'" +
      json +
      "'"
    );
  }

  private openCodeWindowsMergeCommand(): string {
    const json = JSON.stringify(this.buildOpenCodeConfig(false)).replace(/'/g, "''");
    return (
      "$p=Join-Path $env:USERPROFILE '.config\\opencode\\opencode.json'; " +
      "$add='" +
      json +
      "' | ConvertFrom-Json; " +
      '$cfg=if(Test-Path $p){Get-Content $p -Raw | ConvertFrom-Json}else{[pscustomobject]@{}}; ' +
      'if($add.model -and !$cfg.model){$cfg | Add-Member model $add.model -Force}; ' +
      'if(!$cfg.provider){$cfg | Add-Member provider ([pscustomobject]@{})}; ' +
      '$cfg.provider | Add-Member logos $add.provider.logos -Force; ' +
      'New-Item -Force -ItemType Directory (Split-Path $p) | Out-Null; ' +
      '$cfg | ConvertTo-Json -Depth 12 | Set-Content $p; ' +
      'Write-Host "Logos provider written to $p"'
    );
  }

  downloadOpenCodeConfig() {
    const blob = new Blob([this.openCodeConfigJson()], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'opencode.json';
    a.click();
    URL.revokeObjectURL(url);
  }

  // ── Claude Code ───────────────────────────────────────────────────────────
  contextTokens = computed(() => {
    const m = this.selected();
    if (!m) return 0;
    if (m.context_window && m.context_window > 0) return m.context_window;
    return m.provider_type !== 'cloud' ? 32768 : 128000;
  });

  outputTokens = computed(() => Math.min(32768, Math.floor(this.contextTokens() / 4)));

  windowUnenforced = computed(() => {
    const name = (this.selected()?.model_name ?? '').toLowerCase();
    return name.startsWith('claude-') || name.includes('[1m]');
  });

  ready = computed(() => this.selectedKey() !== null && this.selected() !== null);

  private buildClaudeCodeSettings(): Record<string, unknown> {
    const key = this.selectedKey()?.key_value ?? '';
    const model = this.selected()?.model_name ?? '';

    return {
      env: {
        ANTHROPIC_BASE_URL: this.baseUrl(),
        ANTHROPIC_AUTH_TOKEN: key,
        ANTHROPIC_API_KEY: '',
        ANTHROPIC_MODEL: model,
        ANTHROPIC_DEFAULT_HAIKU_MODEL: model,
        ANTHROPIC_DEFAULT_SONNET_MODEL: model,
        ANTHROPIC_DEFAULT_OPUS_MODEL: model,
        ANTHROPIC_DEFAULT_FABLE_MODEL: model,
        CLAUDE_CODE_MAX_CONTEXT_TOKENS: String(this.contextTokens()),
        CLAUDE_CODE_MAX_OUTPUT_TOKENS: String(this.outputTokens()),
        CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: '1',
      },
      permissions: {
        deny: ['WebSearch'],
      },
    };
  }

  claudeCodeSettingsJson = computed(() => JSON.stringify(this.buildClaudeCodeSettings(), null, 2));
  claudeCodeSettingsLines = computed(() => this.claudeCodeSettingsJson().split('\n'));

  readonly claudeCodeInstallCommands = {
    mac: 'brew install --cask claude-code',
    nativeUnix: 'curl -fsSL https://claude.ai/install.sh | bash',
    windows: 'irm https://claude.ai/install.ps1 | iex',
    winget: 'winget install Anthropic.ClaudeCode',
  } as const;

  readonly claudeCodeMergeCommand = computed(() =>
    this.installTab() === 'windows'
      ? this.claudeCodeWindowsMergeCommand()
      : this.claudeCodePosixMergeCommand(),
  );

  private claudeCodePosixMergeCommand(): string {
    const json = JSON.stringify(this.buildClaudeCodeSettings()).replace(/'/g, "'\\''");
    return (
      "python3 -c 'import json,os,sys;" +
      'p=os.path.expanduser("~/.claude/settings.json");' +
      'add=json.loads(sys.argv[1]);' +
      'cfg=json.load(open(p)) if os.path.exists(p) else {};' +
      'cfg.setdefault("env",{}).update(add["env"]);' +
      'deny=cfg.setdefault("permissions",{}).setdefault("deny",[]);' +
      '[deny.append(x) for x in add["permissions"]["deny"] if x not in deny];' +
      'os.makedirs(os.path.dirname(p),exist_ok=True);' +
      'json.dump(cfg,open(p,"w"),indent=2);' +
      'print("Logos settings written to "+p)\' ' +
      "'" +
      json +
      "'"
    );
  }

  private claudeCodeWindowsMergeCommand(): string {
    const json = JSON.stringify(this.buildClaudeCodeSettings()).replace(/'/g, "''");
    return (
      "$p=Join-Path $env:USERPROFILE '.claude\\settings.json'; " +
      "$add='" +
      json +
      "' | ConvertFrom-Json; " +
      '$cfg=if(Test-Path $p){Get-Content $p -Raw | ConvertFrom-Json}else{[pscustomobject]@{}}; ' +
      'if(!$cfg.env){$cfg | Add-Member env ([pscustomobject]@{})}; ' +
      '$add.env.PSObject.Properties | ForEach-Object { $cfg.env | Add-Member $_.Name $_.Value -Force }; ' +
      'if(!$cfg.permissions){$cfg | Add-Member permissions ([pscustomobject]@{deny=@()})}; ' +
      '$add.permissions.deny | ForEach-Object { if($cfg.permissions.deny -notcontains $_){$cfg.permissions.deny+=$_} }; ' +
      'New-Item -Force -ItemType Directory (Split-Path $p) | Out-Null; ' +
      '$cfg | ConvertTo-Json -Depth 12 | Set-Content $p; ' +
      'Write-Host "Logos settings written to $p"'
    );
  }

  downloadClaudeCodeSettings() {
    const blob = new Blob([this.claudeCodeSettingsJson()], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'settings.json';
    a.click();
    URL.revokeObjectURL(url);
  }

  // ── Lifecycle ─────────────────────────────────────────────────────────────
  async ngOnInit(): Promise<void> {
    try {
      const keys = await this.myKeysService.getMyKeys();
      this.keys.set(keys);
      this.keysLoading.set(false);
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

  private modelsRequestId = 0;

  private async pickKey(key: MyKey): Promise<void> {
    const requestId = ++this.modelsRequestId;
    this.selectedKey.set(key);
    this.models.set([]);
    this.selected.set(null);
    this.modelsLoading.set(true);
    this.modelsError.set(false);
    try {
      const models = await this.myKeysService.getKeyModels(key.id);
      if (requestId !== this.modelsRequestId) return;
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
      if (requestId === this.modelsRequestId) this.modelsError.set(true);
    } finally {
      if (requestId === this.modelsRequestId) this.modelsLoading.set(false);
    }
  }

  selectModel(name: string) {
    this.selected.set(this.models().find((m) => m.model_name === name) ?? null);
  }

  copyCmd(text: string) {
    navigator.clipboard.writeText(text).then(() => {
      this.copiedCmd.set(text);
      setTimeout(() => this.copiedCmd.set(null), 2000);
    });
  }
}
