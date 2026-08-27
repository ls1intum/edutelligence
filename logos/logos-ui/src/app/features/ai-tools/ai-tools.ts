import {
  Component,
  computed,
  inject,
  signal,
  OnInit,
  OnDestroy,
  ChangeDetectionStrategy,
} from '@angular/core';
import { CommonModule } from '@angular/common';
import { MyKeysService } from '../../core/services/my-keys.service';
import { MyKey, ModelAccess } from '../../shared/models/my-key.model';
import { SelectComponent, AppSelectOption } from '../../shared/components/select/select';

export type AiTool = 'claudecode' | 'opencode';
export type OsTab = 'mac' | 'linux' | 'windows';

/** One piece of the finishing confetti. Values are randomised per piece. */
interface ConfettiPiece {
  id: number;
  /** Horizontal start, in % of the viewport width. */
  left: number;
  delay: number;
  duration: number;
  /** Sideways travel while falling, in px. */
  drift: number;
  /** Total rotation, in degrees. */
  spin: number;
  size: number;
  color: string;
}

/** One row of the step-1 comparison, stated for both tools so they line up. */
interface ComparisonRow {
  dimension: string;
  claudecode: string;
  opencode: string;
  /** Which side this row favours, for the ✓/○ marker. 'even' marks neither. */
  favours: AiTool | 'even';
}

@Component({
  selector: 'app-ai-tools',
  standalone: true,
  imports: [CommonModule, SelectComponent],
  templateUrl: './ai-tools.html',
  changeDetection: ChangeDetectionStrategy.Eager,
  styleUrl: './ai-tools.scss',
})
export class AiTools implements OnInit, OnDestroy {
  private myKeysService = inject(MyKeysService);

  readonly String = String;

  // ── Wizard ────────────────────────────────────────────────────────────────
  // The page walks one decision at a time: tool, then team, then model, then the
  // mechanics. Earlier steps stay reachable (their summary line is a button) but
  // a later one cannot be opened before the choices it is generated from exist.
  //
  // Ids are fixed and never renumbered — they are how the template and the
  // gating below refer to a step. What the user sees is numbered in
  // `visibleSteps`, which leaves out the steps that hold no decision.
  readonly allSteps = [
    { id: 1, title: 'Tool' },
    { id: 2, title: 'Team' },
    { id: 3, title: 'Model' },
    { id: 4, title: 'Install' },
    { id: 5, title: 'Connect' },
    { id: 6, title: 'Verify' },
  ] as const;

  readonly LAST_STEP = 6;

  step = signal<number>(1);

  activeTool = signal<AiTool | null>(null);

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
  installTab = signal<OsTab>(navigatorOs());
  connectMethod = signal<'download' | 'terminal'>('terminal');
  copiedCmd = signal<string | null>(null);

  // ── Step gating ───────────────────────────────────────────────────────────
  readonly toolChosen = computed(() => this.activeTool() !== null);
  readonly teamChosen = computed(() => this.selectedKey() !== null);
  readonly modelChosen = computed(() => this.selected() !== null);
  readonly ready = computed(() => this.teamChosen() && this.modelChosen());

  /**
   * A step that holds no decision is not a step. With one team there is nothing
   * to pick in step 2; with one model, nothing in step 3. Asking anyway is a
   * click that can only be answered one way.
   *
   * Only while the list is loaded and holds exactly one entry. An empty list is
   * *not* skipped — that step is where "no keys for your account" is said, and
   * silently jumping over it would leave the user in a later step wondering why
   * nothing is generated.
   */
  isSkipped(step: number): boolean {
    if (step === 2) return !this.keysLoading() && this.keys().length === 1;
    if (step === 3) return !this.modelsLoading() && this.models().length === 1;
    return false;
  }

  /** The steps as the user sees them: skipped ones gone, the rest renumbered. */
  readonly visibleSteps = computed(() =>
    this.allSteps
      .filter((s) => !this.isSkipped(s.id))
      .map((s, index) => ({ ...s, number: index + 1 })),
  );

  /** Displayed position of a step, for headings and summary lines. */
  stepNumber(step: number): number {
    return this.visibleSteps().find((s) => s.id === step)?.number ?? step;
  }

  canOpen(step: number): boolean {
    if (this.isSkipped(step)) return false;
    if (step <= 1) return true;
    if (!this.toolChosen()) return false;
    if (step === 2) return true;
    if (!this.teamChosen()) return false;
    if (step === 3) return true;
    return this.modelChosen();
  }

  stepState(step: number): 'done' | 'current' | 'locked' | 'upcoming' {
    if (step === this.step()) return 'current';
    if (!this.canOpen(step)) return 'locked';
    return step < this.step() ? 'done' : 'upcoming';
  }

  /**
   * Whether a collapsed step shows its one-line summary. Only for steps already
   * behind us: a summary on a step not yet reached would read as a decision that
   * has been made when it has not.
   */
  showSummary(step: number): boolean {
    return this.step() > step && this.canOpen(step);
  }

  goTo(step: number): void {
    if (this.canOpen(step)) this.setStep(step);
  }

  next(): void {
    const target = this.firstOpenFrom(this.step() + 1);
    if (target !== null) this.setStep(target);
  }

  back(): void {
    for (let candidate = this.step() - 1; candidate >= 1; candidate--) {
      if (this.canOpen(candidate)) {
        this.setStep(candidate);
        return;
      }
    }
  }

  /** First step at or after `from` the user can actually open. */
  private firstOpenFrom(from: number): number | null {
    for (let candidate = from; candidate <= this.LAST_STEP; candidate++) {
      if (this.canOpen(candidate)) return candidate;
    }
    return null;
  }

  private setStep(step: number): void {
    this.step.set(step);
    // Reaching the last step means the setup is done — everything after it is
    // reading, not doing.
    if (step === this.LAST_STEP) this.celebrate();
  }

  // ── Step 1: tool comparison ───────────────────────────────────────────────
  // Same dimensions in the same order on both sides, so the two columns can be
  // read across rather than as two separate marketing lists.
  readonly comparison: ComparisonRow[] = [
    {
      dimension: 'Interface',
      claudecode: 'Terminal, plus VS Code and JetBrains extensions',
      opencode: 'Desktop app and terminal',
      favours: 'opencode',
    },
    {
      dimension: 'Switching model',
      claudecode: 'One model per session — restart to change it',
      opencode: 'Model picker at any time, several providers side by side',
      favours: 'opencode',
    },
    {
      dimension: 'Context window',
      claudecode: 'Asked for at every start, so it always matches what Logos can give you today',
      opencode: 'Written into the config file once, so it can drift from what Logos can give you',
      favours: 'claudecode',
    },
    {
      dimension: 'Where prompts go',
      claudecode: 'Always Logos — the wrapper is bound to it',
      opencode: 'Logos only while a Logos model is selected; other models go to their own clouds',
      favours: 'claudecode',
    },
    {
      dimension: 'Effect on your setup',
      claudecode: 'None — `claude` keeps using your Anthropic subscription unchanged',
      opencode: 'Adds a provider to your opencode.json',
      favours: 'claudecode',
    },
    {
      dimension: 'Agent features',
      claudecode: 'Subagents, hooks, skills, MCP',
      opencode: 'MCP, smaller agent toolkit',
      favours: 'claudecode',
    },
  ];

  /** Both tools, in the order the comparison cards are laid out. */
  readonly toolChoices: readonly AiTool[] = ['claudecode', 'opencode'];

  readonly toolSummaries: Record<AiTool, { headline: string; caveat: string }> = {
    claudecode: {
      headline: 'Runs entirely on Logos and sizes each session to the context Logos can give it.',
      caveat: 'Terminal only, one model per session.',
    },
    opencode: {
      headline: 'Desktop app, and you can switch models mid-session.',
      caveat: 'Prompts leave Logos as soon as you pick a non-Logos model.',
    },
  };

  chooseTool(tool: AiTool): void {
    this.activeTool.set(tool);
    // A tool switch changes what the later steps say but nothing about the team
    // or the model, so those choices are kept. Land on the next step that
    // actually asks something — with one team and one model that is the install.
    const target = this.firstOpenFrom(2);
    if (target !== null) this.setStep(target);
  }

  toolLabel(tool: AiTool | null): string {
    return tool === 'claudecode' ? 'Claude Code' : tool === 'opencode' ? 'OpenCode' : '—';
  }

  // ── URLs ──────────────────────────────────────────────────────────────────
  // /v1 is never routed on the admin entrypoint (:9443) this page is served on in
  // prod; that port is stripped. In dev, UI and /v1 share one port, so origin is
  // left untouched.
  baseUrl = computed(() => window.location.origin.replace(/:9443$/, ''));
  baseUrlV1 = computed(() => this.baseUrl() + '/v1');

  // ── Options ───────────────────────────────────────────────────────────────
  readonly keyOptions = computed<AppSelectOption[]>(() =>
    this.keys().map((k) => ({ value: String(k.id), label: k.team.name })),
  );

  readonly modelOptions = computed<AppSelectOption[]>(() =>
    this.models().map((m) => ({ value: m.model_name, label: m.model_name })),
  );

  // ── Context windows ───────────────────────────────────────────────────────
  // Three numbers per model, and which one to use depends on who is asking.
  //
  // How much context Logos can give a model depends on how much capacity is
  // free, so the same model can be served at 262,144 tokens and at a fraction
  // of that at the same time. contextCurrentMin is the floor — the only figure
  // that holds whichever deployment answers. contextCurrentMax is the widest
  // being served now, which long requests are routed towards. contextOverall is
  // the widest it is ever served with, known even while nothing is loaded.
  contextCurrentMin = computed(() => positive(this.selected()?.context_window_current_min));
  contextCurrentMax = computed(
    () => positive(this.selected()?.context_window_current_max) || this.contextCurrentMin(),
  );
  contextOverall = computed(
    () => positive(this.selected()?.context_window_overall) || this.contextCurrentMax(),
  );

  /**
   * Whether the three figures above rest on anything Logos reported.
   *
   * Two separate questions, because they stop being true at different times.
   * The current_* pair describes lanes that are up right now, so it is empty
   * whenever the model is not loaded — which is most of the time for a model
   * nobody is using. context_window_overall comes from the model's own profile
   * and survives that: the orchestrator keeps reporting it with no lane in
   * sight. Tying the maximum to hasCurrentWindow would throw away the one
   * number that is still known and print a fallback instead, which is how a
   * 262,144-token model came to be shown as 32,768.
   */
  hasCurrentWindow = computed(() => this.contextCurrentMin() > 0);
  hasOverallWindow = computed(() => this.contextOverall() > 0);

  /**
   * The window to write into a config file that is only read at startup: the
   * widest this model is ever served with, or a conservative stand-in when
   * Logos reports nothing for it.
   */
  static configuredContextFor(model: ModelAccess): number {
    return (
      positive(model.context_window_overall) ||
      positive(model.context_window_current_max) ||
      positive(model.context_window_current_min) ||
      (model.provider_type !== 'cloud' ? 32768 : 128000)
    );
  }

  /** The stand-in above, for display when nothing is reported. */
  contextFallback = computed(() => (this.selected()?.provider_type !== 'cloud' ? 32768 : 128000));

  windowUnenforced = computed(() => {
    const name = (this.selected()?.model_name ?? '').toLowerCase();
    return name.startsWith('claude-') || name.includes('[1m]');
  });

  // ── OpenCode ──────────────────────────────────────────────────────────────
  private buildOpenCodeConfig(withSchema: boolean): Record<string, unknown> {
    const key = this.selectedKey()?.key_value ?? '';
    const allModels = this.models();
    const defModel = this.selected();

    const modelsMap: Record<string, { name: string; limit: { context: number; output: number } }> =
      {};
    for (const m of allModels) {
      // The widest this model is ever served with: OpenCode reads its config
      // once at startup, so a number that tracks what happens to be loaded
      // right now would be wrong by the time it matters. Long requests are
      // routed to wherever there is room for them.
      const context = AiTools.configuredContextFor(m);
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
  readonly claudeCodeInstallCommands = {
    mac: 'brew install --cask claude-code',
    nativeUnix: 'curl -fsSL https://claude.ai/install.sh | bash',
    windows: 'irm https://claude.ai/install.ps1 | iex',
    winget: 'winget install Anthropic.ClaudeCode',
  } as const;

  wrapperUrl = computed(
    () => this.baseUrl() + (this.installTab() === 'windows' ? '/claude-logos.ps1' : '/claude-logos.sh'),
  );

  /**
   * Installs the `claude-logos` wrapper: one small script on the PATH that
   * exports the Logos endpoint, credential and context window into its own child
   * process and then hands every argument straight to `claude`.
   *
   * Deliberately NOT an env block in ~/.claude/settings.json, which is how this
   * page used to do it. That file is global: it redirects every Claude Code
   * session on the machine to Logos, so a user with an Anthropic subscription has
   * to edit it back and forth to use both. A wrapper leaves plain `claude`
   * untouched — `claude` stays on the subscription, `claude-logos` goes to Logos.
   */
  readonly claudeCodeInstallCommand = computed(() =>
    this.installTab() === 'windows'
      ? this.claudeCodeWindowsInstall()
      : this.claudeCodePosixInstall(),
  );

  private claudeCodePosixInstall(): string {
    const key = this.selectedKey()?.key_value ?? '';
    const model = this.selected()?.model_name ?? '';
    return [
      `curl -fsSL ${this.wrapperUrl()} -o ~/.claude-logos-install.sh \\`,
      // Quoted delimiter: an unquoted heredoc would let the shell expand a `$`
      // or a backtick inside the key before the wrapper ever sees it.
      "  && bash ~/.claude-logos-install.sh --install <<'LOGOS'",
      `LOGOS_URL=${this.baseUrl()}`,
      `LOGOS_MODEL=${model}`,
      `LOGOS_KEY=${key}`,
      'LOGOS',
      'rm -f ~/.claude-logos-install.sh',
    ].join('\n');
  }

  private claudeCodeWindowsInstall(): string {
    const key = this.selectedKey()?.key_value ?? '';
    const model = this.selected()?.model_name ?? '';
    return [
      "$p = Join-Path $env:TEMP 'claude-logos-install.ps1'",
      `Invoke-WebRequest -UseBasicParsing '${this.wrapperUrl()}' -OutFile $p`,
      "& $p -Install -LogosConfig @'",
      `LOGOS_URL=${this.baseUrl()}`,
      `LOGOS_MODEL=${model}`,
      `LOGOS_KEY=${key}`,
      "'@",
      'Remove-Item $p',
    ].join('\n');
  }

  readonly claudeCodeUninstallCommand = computed(() =>
    this.installTab() === 'windows'
      ? `& "$env:LOCALAPPDATA\\Programs\\claude-logos\\claude-logos.ps1" -Uninstall`
      : 'claude-logos --uninstall',
  );

  readonly claudeCodeUpdateCommand = computed(() =>
    this.installTab() === 'windows'
      ? '& "$env:LOCALAPPDATA\\Programs\\claude-logos\\claude-logos.ps1" -Update'
      : 'claude-logos --update',
  );

  readonly claudeCodeVerifyCommand = computed(() =>
    this.installTab() === 'windows'
      ? '& "$env:LOCALAPPDATA\\Programs\\claude-logos\\claude-logos.ps1" -Check'
      : 'claude-logos --check',
  );

  // Paths and one-liners that contain backslashes or angle brackets. Kept here
  // rather than inline in the template, where both need escaping to survive the
  // HTML and control-flow parsers.
  readonly wrapperInstallDir = computed(() =>
    this.installTab() === 'windows'
      ? '%LOCALAPPDATA%\\Programs\\claude-logos'
      : '~/.local/bin/claude-logos',
  );

  readonly wrapperConfigDir = computed(() =>
    this.installTab() === 'windows'
      ? '%USERPROFILE%\\.config\\claude-logos'
      : '~/.config/claude-logos',
  );

  readonly modelOverrideExample = computed(() =>
    this.installTab() === 'windows'
      ? "$env:LOGOS_MODEL='<model>'; claude-logos"
      : 'LOGOS_MODEL=<model> claude-logos',
  );

  readonly openCodeConfigPath = computed(() =>
    this.installTab() === 'windows'
      ? '%USERPROFILE%\\.config\\opencode\\opencode.json'
      : '~/.config/opencode/opencode.json',
  );

  readonly osLabel = computed(() =>
    this.installTab() === 'mac' ? 'macOS' : this.installTab() === 'linux' ? 'Linux' : 'Windows',
  );

  readonly shellPrompt = computed(() => (this.installTab() === 'windows' ? '>' : '$'));

  // ── Finishing ─────────────────────────────────────────────────────────────
  // A small burst of confetti when the last step opens. Rendered inside the
  // component so the component's own stylesheet applies — appending to
  // document.body would put the nodes outside Angular's style encapsulation.
  confetti = signal<ConfettiPiece[]>([]);
  private celebrated = false;
  private confettiTimer: ReturnType<typeof setTimeout> | null = null;

  private celebrate(): void {
    // Once per visit. Stepping back and forth should not set it off again.
    if (this.celebrated) return;
    this.celebrated = true;
    // Someone who asked their system for less motion means it.
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return;

    // The palette tokens are bare RGB triples ("124 58 237"), so they need the
    // rgb() wrapper here the same way every stylesheet in the app does.
    const colors = [
      'rgb(var(--color-primary-500))',
      'rgb(var(--color-primary-400))',
      'rgb(var(--color-accent-green))',
      'rgb(var(--color-warning))',
    ];
    this.confetti.set(
      Array.from({ length: 36 }, (_, index) => ({
        id: index,
        left: Math.random() * 100,
        delay: Math.random() * 0.5,
        duration: 2 + Math.random() * 1.2,
        drift: Math.random() * 120 - 60,
        spin: Math.random() * 720 - 360,
        size: 5 + Math.random() * 4,
        color: colors[index % colors.length],
      })),
    );
    // Drop the nodes once the longest piece has fallen, so nothing lingers in
    // the DOM for the rest of the session.
    this.confettiTimer = setTimeout(() => this.confetti.set([]), 4000);
  }

  ngOnDestroy(): void {
    if (this.confettiTimer !== null) clearTimeout(this.confettiTimer);
  }

  // ── Lifecycle ─────────────────────────────────────────────────────────────
  async ngOnInit(): Promise<void> {
    try {
      const keys = await this.myKeysService.getMyKeys();
      this.keys.set(keys);
      this.keysLoading.set(false);
      // Pre-select when there is nothing to decide, so a single-team user does
      // not have to confirm a list of one.
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

function positive(value: number | null | undefined): number {
  return typeof value === 'number' && value > 0 ? value : 0;
}

/** Best guess at the visitor's OS, so the install tab starts on the right one. */
function navigatorOs(): OsTab {
  const platform = `${navigator.platform} ${navigator.userAgent}`.toLowerCase();
  if (platform.includes('win')) return 'windows';
  if (platform.includes('linux') && !platform.includes('android')) return 'linux';
  return 'mac';
}
