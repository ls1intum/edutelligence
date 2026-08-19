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
  selector: 'app-claude-code',
  standalone: true,
  imports: [CommonModule, SelectComponent],
  templateUrl: './claude-code.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './claude-code.scss',
})
export class ClaudeCode implements OnInit {
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

  // Claude Code talks the Anthropic Messages API and appends /v1/messages to
  // ANTHROPIC_BASE_URL itself, so unlike the OpenCode page this URL must NOT
  // carry a /v1 suffix. The :9443 admin entrypoint this page may be served on
  // in prod never routes /v1, so that port is stripped; in dev the UI and /v1
  // share one port and the origin is left untouched.
  baseUrl = computed(() => window.location.origin.replace(/:9443$/, ''));

  // Claude Code assumes a 200k window for models it doesn't know, so requests
  // overflow upstream long before it decides to compact. The window a model
  // really serves is reported by the orchestrator; models without one get a
  // conservative fallback (32768 local, 128000 cloud) matching the OpenCode page.
  // Input and output share this one budget upstream — vLLM counts both against
  // --max-model-len — so the output cap is reserved out of the window rather
  // than added on top, and capped at 32768 so long sessions keep room to think.
  contextTokens = computed(() => {
    const m = this.selected();
    if (!m) return 0;
    if (m.context_window && m.context_window > 0) return m.context_window;
    return m.provider_type !== 'cloud' ? 32768 : 128000;
  });

  outputTokens = computed(() => Math.min(32768, Math.floor(this.contextTokens() / 4)));

  // CLAUDE_CODE_MAX_CONTEXT_TOKENS only applies directly to a model id that
  // Claude Code cannot resolve to a Claude model. An id starting with "claude-"
  // needs DISABLE_COMPACT as well, and one containing "[1m]" needs
  // CLAUDE_CODE_DISABLE_1M_CONTEXT — neither is something this page should set
  // silently, so it warns instead. No Logos model is named that way today; this
  // guards against one being registered later.
  windowUnenforced = computed(() => {
    const name = (this.selected()?.model_name ?? '').toLowerCase();
    return name.startsWith('claude-') || name.includes('[1m]');
  });

  // Both a key and a model are required before any settings can be written.
  // Without this the page would happily generate a config with an empty token
  // and an empty model name, and offer it for download — overwriting a working
  // ~/.claude/settings.json with one that cannot authenticate.
  ready = computed(() => this.selectedKey() !== null && this.selected() !== null);

  maskedKey = computed(() => {
    const k = this.selectedKey()?.key_value ?? '';
    return k.length > 14 ? k.slice(0, 14) + ' ···' : k;
  });

  private buildSettings(): Record<string, unknown> {
    const key = this.selectedKey()?.key_value ?? '';
    const model = this.selected()?.model_name ?? '';

    return {
      env: {
        ANTHROPIC_BASE_URL: this.baseUrl(),
        // Sends the key as "Authorization: Bearer", which is what the Logos
        // orchestrator reads. ANTHROPIC_API_KEY would use x-api-key instead, so
        // it is blanked to stop a globally exported value from winning.
        ANTHROPIC_AUTH_TOKEN: key,
        ANTHROPIC_API_KEY: '',
        // Every model slot points at the same Logos model: the primary one plus
        // the aliases behind /model, so switching alias never leaves Logos.
        ANTHROPIC_MODEL: model,
        ANTHROPIC_DEFAULT_HAIKU_MODEL: model,
        ANTHROPIC_DEFAULT_SONNET_MODEL: model,
        ANTHROPIC_DEFAULT_OPUS_MODEL: model,
        ANTHROPIC_DEFAULT_FABLE_MODEL: model,
        CLAUDE_CODE_MAX_CONTEXT_TOKENS: String(this.contextTokens()),
        CLAUDE_CODE_MAX_OUTPUT_TOKENS: String(this.outputTokens()),
        // Keeps telemetry and model discovery off api.anthropic.com, so the only
        // traffic leaving the machine goes to Logos.
        CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: '1',
      },
      permissions: {
        // WebSearch is a server-side Anthropic tool: Claude Code sends it as
        // {"type":"web_search_20250305"} with no input_schema, which the worker
        // nodes reject with HTTP 400, and Claude Code then retries in a loop.
        // Denying it keeps the tool out of the request entirely.
        deny: ['WebSearch'],
      },
    };
  }

  settingsJson = computed(() => JSON.stringify(this.buildSettings(), null, 2));

  settingsLines = computed(() => this.settingsJson().split('\n'));

  readonly keyOptions = computed<AppSelectOption[]>(() =>
    this.keys().map((k) => ({ value: String(k.id), label: k.name })),
  );

  readonly modelOptions = computed<AppSelectOption[]>(() =>
    this.models().map((m) => ({ value: m.model_name, label: m.model_name })),
  );

  readonly installCommands = {
    mac: 'brew install --cask claude-code',
    nativeUnix: 'curl -fsSL https://claude.ai/install.sh | bash',
    windows: 'irm https://claude.ai/install.ps1 | iex',
    winget: 'winget install Anthropic.ClaudeCode',
  } as const;

  // Merges only the Logos parts into an existing settings file: the env keys are
  // set/updated, WebSearch is added to permissions.deny if missing, everything
  // else in the file stays untouched. Creates file and directory if missing.
  // Uses tools the OS already has (python3 / PowerShell) so Node.js is not required.
  readonly mergeCommand = computed(() =>
    this.installTab() === 'windows' ? this.windowsMergeCommand() : this.posixMergeCommand(),
  );

  private posixMergeCommand(): string {
    // The JSON is passed as argv inside shell single quotes, so a literal ' in
    // the data (model names are admin-defined) must become '\''.
    const json = JSON.stringify(this.buildSettings()).replace(/'/g, "'\\''");
    return (
      "python3 -c 'import json,os,sys;" +
      'p=os.path.expanduser("~/.claude/settings.json");' +
      'add=json.loads(sys.argv[1]);' +
      'cfg=json.load(open(p)) if os.path.exists(p) else {};' +
      'cfg.setdefault("env",{}).update(add["env"]);' +
      'd=cfg.setdefault("permissions",{}).setdefault("deny",[]);' +
      '"WebSearch" in d or d.append("WebSearch");' +
      'os.makedirs(os.path.dirname(p),exist_ok=True);' +
      'json.dump(cfg,open(p,"w"),indent=2);' +
      'print("Logos settings written to "+p)\' ' +
      "'" + json + "'"
    );
  }

  private windowsMergeCommand(): string {
    // In a PowerShell single-quoted string a literal ' is escaped by doubling.
    const json = JSON.stringify(this.buildSettings()).replace(/'/g, "''");
    return (
      "$p=Join-Path $env:USERPROFILE '.claude\\settings.json'; " +
      "$add='" + json + "' | ConvertFrom-Json; " +
      '$cfg=if(Test-Path $p){Get-Content $p -Raw | ConvertFrom-Json}else{[pscustomobject]@{}}; ' +
      'if(!$cfg.env){$cfg | Add-Member env ([pscustomobject]@{}) -Force}; ' +
      'foreach($k in $add.env.PSObject.Properties.Name){$cfg.env | Add-Member $k $add.env.$k -Force}; ' +
      'if(!$cfg.permissions){$cfg | Add-Member permissions ([pscustomobject]@{}) -Force}; ' +
      'if(!$cfg.permissions.deny){$cfg.permissions | Add-Member deny @() -Force}; ' +
      "if($cfg.permissions.deny -notcontains 'WebSearch'){$cfg.permissions.deny=@($cfg.permissions.deny)+'WebSearch'}; " +
      'New-Item -Force -ItemType Directory (Split-Path $p) | Out-Null; ' +
      '$cfg | ConvertTo-Json -Depth 12 | Set-Content $p; ' +
      'Write-Host "Logos settings written to $p"'
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

  // Incremented on every key switch. A model fetch that resolves after a newer
  // switch started is discarded: otherwise picking key A then key B can leave
  // B paired with A's models, and the generated settings would name a model
  // that key B has no access to.
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
      // On duplicate names keep the local entry: the served window falls back to
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
      if (requestId === this.modelsRequestId) this.modelsError.set(true);
    } finally {
      if (requestId === this.modelsRequestId) this.modelsLoading.set(false);
    }
  }

  selectModel(name: string) {
    this.selected.set(this.models().find((m) => m.model_name === name) ?? null);
  }

  downloadSettings() {
    const blob = new Blob([this.settingsJson()], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'settings.json';
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
