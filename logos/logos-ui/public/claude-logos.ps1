<#
.SYNOPSIS
  Run Claude Code against a Logos gateway instead of api.anthropic.com (Windows).

.DESCRIPTION
  The PowerShell counterpart of claude-logos.sh. Logos serves the Anthropic Messages
  API natively at POST /v1/messages, so there is no proxy in between: Claude Code talks
  to Logos directly.

    claude-logos                     interactive session
    claude-logos -p "..."            headless / one-shot
    claude-logos --resume            every claude flag is passed through unchanged

    claude-logos -Check              show the connection, the model and how much
                                     context this session would get, then exit
    claude-logos -Install            install to %LOCALAPPDATA%\Programs\claude-logos
                                     (takes KEY=value lines via -LogosConfig)
    claude-logos -Update             replace this wrapper with the current one
    claude-logos -Uninstall          remove the wrapper, its config and its key

  NOTHING OUTSIDE THIS WRAPPER IS TOUCHED. The Logos credential, base URL and model are
  set on this process only — never with [Environment]::SetEnvironmentVariable at User or
  Machine scope — and the extra Claude Code settings live in this wrapper's own folder
  and are handed over with --settings. Your PowerShell profile,
  %USERPROFILE%\.claude\settings.json and your claude.ai login are left exactly as they
  are, so plain `claude` keeps using your Anthropic subscription.

  It never updates itself either. It notices when Logos serves a newer revision
  and says so; replacing it is always something you type.

  This file is served by the Logos UI at <logos-url>/claude-logos.ps1 and is what the
  "AI Tools" page installs.
#>
[CmdletBinding(PositionalBinding = $false)]
param(
    [switch]$Install,
    [switch]$Uninstall,
    [switch]$Update,
    [switch]$Check,
    [switch]$Yes,
    # KEY=value lines for -Install, passed as a here-string. Keeping it a
    # parameter rather than a pipeline read makes the install a single call that
    # behaves the same from the console, from a .cmd shim and from a script.
    [string]$LogosConfig,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$ClaudeArgs
)

$ErrorActionPreference = 'Stop'

# Bump on every change installed copies should pick up. Keep in step with the same
# constant in claude-logos.sh — the two wrappers are one tool with two front ends.
# A monotonic integer, not a version string: the comparison cannot misread anything.
$ClaudeLogosVersion = 2          # 2026-09-04

$ConfigDir = if ($env:LOGOS_CONFIG_DIR) { $env:LOGOS_CONFIG_DIR }
             else { Join-Path $env:USERPROFILE '.config\claude-logos' }
$ConfigFile = Join-Path $ConfigDir 'config'
$KeyFile = Join-Path $ConfigDir 'key'
$SettingsFile = Join-Path $ConfigDir 'settings.json'
$KnownModelsFile = Join-Path $ConfigDir 'known-models'
$VersionStateFile = Join-Path $ConfigDir 'latest-revision'
$InstallDir = if ($env:LOGOS_INSTALL_DIR) { $env:LOGOS_INSTALL_DIR }
              else { Join-Path $env:LOCALAPPDATA 'Programs\claude-logos' }
$InstallPath = Join-Path $InstallDir 'claude-logos.ps1'
$ShimPath = Join-Path $InstallDir 'claude-logos.cmd'

function Write-Note([string]$Message) { Write-Host "claude-logos: $Message" }
function Stop-WithError([string]$Message) { Write-Error "claude-logos: $Message"; exit 1 }

# ── Settings, lowest precedence first ────────────────────────────────────────────
# The config file is written by -Install (i.e. by the AI Tools page) and holds
# KEY=value lines. Environment variables win over it, so a single invocation can be
# redirected without editing anything:
#
#   $env:LOGOS_MODEL = 'openai/gpt-oss-120b'; claude-logos
#
$Config = @{}
if (Test-Path -LiteralPath $ConfigFile) {
    foreach ($line in Get-Content -LiteralPath $ConfigFile) {
        if ($line -match '^([A-Z_][A-Z0-9_]*)=(.*)$') { $Config[$Matches[1]] = $Matches[2] }
    }
}
function Get-Setting([string]$Name, $Default) {
    $fromEnv = [Environment]::GetEnvironmentVariable($Name)
    if ($fromEnv) { return $fromEnv }
    if ($Config.ContainsKey($Name) -and $Config[$Name]) { return $Config[$Name] }
    return $Default
}

$LogosUrl = (Get-Setting 'LOGOS_URL' 'https://logos.aet.cit.tum.de').TrimEnd('/')
$LogosModel = Get-Setting 'LOGOS_MODEL' ''

# Which context size to run the session at: 'available' (what Logos can give this
# model at the moment — the default, since long requests are sent wherever there is
# room for them), 'guaranteed' (the size you always get, whatever the load) or 'max'
# (the most this model can ever offer). See claude-logos.sh for the full reasoning.
$ContextSource = Get-Setting 'LOGOS_CONTEXT_SOURCE' 'available'
$ContextFallback = [int](Get-Setting 'LOGOS_CONTEXT_FALLBACK' 111200)

# Claude Code caps what it reserves for output at 20000 tokens no matter how large a
# CLAUDE_CODE_MAX_OUTPUT_TOKENS it is given, and subtracts that reservation from the
# window itself. Asking for more buys nothing and costs context. Lowering it is the
# one knob that makes a narrow window usable: under ~37000 tokens the default leaves
# less input room than Claude Code's own opening prompt and the session is refused
# before it starts (see the floor check below, which prints the value that fits).
$MaxOutputTokens = [int](Get-Setting 'LOGOS_MAX_OUTPUT_TOKENS' 20000)

# Logos rejects reasoning effort "high" with HTTP 500 before the model sees anything,
# so a session left on high fails on every turn. xhigh is its default and the closest
# match. Set LOGOS_EFFORT to an empty string to opt out.
$Effort = Get-Setting 'LOGOS_EFFORT' 'xhigh'

# ── Revision check ──────────────────────────────────────────────────────────────
# Logos serves the current wrapper at the same URL this copy came from, so the
# revision in that file is the only source of truth. Nothing here ever replaces
# this script.
#
# Unlike the bash wrapper this check is synchronous: PowerShell's background jobs
# each cost a whole extra process, which is more than the check itself. It runs at
# most once a day and the request is a few tens of kilobytes, so the cost is a
# round trip on one start out of however many happen in 24 hours.
function Get-RemoteRevision([string]$Text) {
    if ($Text -match '(?m)^\$ClaudeLogosVersion\s*=\s*(\d+)') { return [int]$Matches[1] }
    return 0
}

function Get-CachedRevision {
    if (-not (Test-Path -LiteralPath $VersionStateFile)) { return 0 }
    $raw = (Get-Content -Raw -LiteralPath $VersionStateFile).Trim() -split "`t"
    if ($raw.Count -ge 1 -and $raw[0] -match '^\d+$') { return [int]$raw[0] }
    return 0
}

function Report-NewRevision {
    $latest = Get-CachedRevision
    if ($latest -le $ClaudeLogosVersion) { return }
    Write-Host ("update   : claude-logos revision {0} is available (this is {1})" -f $latest, $ClaudeLogosVersion)
    Write-Host '           run: claude-logos -Update    (nothing changes until you do)'
}

function Update-CachedRevision {
    $intervalSeconds = [int](Get-Setting 'LOGOS_VERSION_CHECK_INTERVAL' 86400)
    $now = [int][double]::Parse((Get-Date -UFormat %s))
    if (Test-Path -LiteralPath $VersionStateFile) {
        $raw = (Get-Content -Raw -LiteralPath $VersionStateFile).Trim() -split "`t"
        if ($raw.Count -ge 2 -and $raw[1] -match '^\d+$' -and ($now - [int]$raw[1]) -le $intervalSeconds) {
            return
        }
    }
    try {
        $text = Invoke-RestMethod -Uri "$LogosUrl/claude-logos.ps1" -TimeoutSec 10
        $remote = Get-RemoteRevision "$text"
        if ($remote -gt 0) {
            Set-Content -LiteralPath $VersionStateFile -Value "$remote`t$now" -Encoding UTF8
        }
    } catch {
        # Offline, or Logos is not reachable: say nothing and try again tomorrow.
    }
}

# ── -Update ─────────────────────────────────────────────────────────────────────
# Replaces this file and nothing else: the key, the config and the settings layer
# stay as they are, so an update is not a re-setup.
function Invoke-LogosUpdate {
    $target = if (Test-Path -LiteralPath $InstallPath) { $InstallPath } else { $PSCommandPath }
    $staged = Join-Path (Split-Path $target) ("claude-logos.{0}.tmp" -f [System.IO.Path]::GetRandomFileName())
    try {
        Invoke-WebRequest -UseBasicParsing -Uri "$LogosUrl/claude-logos.ps1" -OutFile $staged -TimeoutSec 60
    } catch {
        if (Test-Path -LiteralPath $staged) { Remove-Item -LiteralPath $staged -Force }
        Stop-WithError "could not download $LogosUrl/claude-logos.ps1 ($($_.Exception.Message))"
    }

    # Validate before replacing anything. A captive portal or a proxy error page
    # would otherwise leave a working wrapper overwritten with HTML — and this file
    # is the next thing the user runs.
    $remote = Get-RemoteRevision (Get-Content -Raw -LiteralPath $staged)
    if ($remote -le 0) {
        Remove-Item -LiteralPath $staged -Force
        Stop-WithError "what $LogosUrl served is not a claude-logos script"
    }
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile($staged, [ref]$null, [ref]$errors) | Out-Null
    if ($errors -and $errors.Count -gt 0) {
        Remove-Item -LiteralPath $staged -Force
        Stop-WithError 'the downloaded script does not parse — not installing it'
    }

    if ($remote -eq $ClaudeLogosVersion) {
        Remove-Item -LiteralPath $staged -Force
        if (Test-Path -LiteralPath $VersionStateFile) { Remove-Item -LiteralPath $VersionStateFile -Force }
        Write-Host ("Already current (revision {0})." -f $ClaudeLogosVersion)
        return
    }

    Move-Item -LiteralPath $staged -Destination $target -Force
    if (Test-Path -LiteralPath $VersionStateFile) { Remove-Item -LiteralPath $VersionStateFile -Force }
    Write-Host ("Updated {0}: revision {1} -> {2}" -f $target, $ClaudeLogosVersion, $remote)
    Write-Host 'Your key, model and settings were not touched.'
}

# ── -Install ────────────────────────────────────────────────────────────────────
# Takes KEY=value lines from -LogosConfig, or from stdin when that is empty.
function Invoke-LogosInstall([string]$ConfigText) {
    if (-not $ConfigText -and [Console]::IsInputRedirected) {
        $ConfigText = [Console]::In.ReadToEnd()
    }
    $url = ''; $model = ''; $key = ''
    foreach ($line in ($ConfigText -split "`r?`n")) {
        if ($line -match '^LOGOS_URL=(.*)$') { $url = $Matches[1] }
        elseif ($line -match '^LOGOS_MODEL=(.*)$') { $model = $Matches[1] }
        elseif ($line -match '^LOGOS_KEY=(.*)$') { $key = $Matches[1] }
    }
    if (-not $key) { Stop-WithError '-Install needs a LOGOS_KEY=… line in -LogosConfig' }
    if (-not $url) { Stop-WithError '-Install needs a LOGOS_URL=… line in -LogosConfig' }

    New-Item -ItemType Directory -Force -Path $InstallDir, $ConfigDir | Out-Null
    if ($PSCommandPath -ne $InstallPath) {
        Copy-Item -LiteralPath $PSCommandPath -Destination $InstallPath -Force
    }

    # A .cmd shim so `claude-logos` works from cmd.exe and from PowerShell alike,
    # without the caller having to type powershell -File.
    @'
@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0claude-logos.ps1" %*
'@ | Set-Content -LiteralPath $ShimPath -Encoding ASCII

    Set-Content -LiteralPath $KeyFile -Value $key.Trim() -NoNewline -Encoding UTF8
    Protect-UserOnly $KeyFile

    $configLines = @(
        '# Written by claude-logos -Install. Environment variables win over this file.',
        "LOGOS_URL=$($url.TrimEnd('/'))"
    )
    if ($model) { $configLines += "LOGOS_MODEL=$model" }
    Set-Content -LiteralPath $ConfigFile -Value $configLines -Encoding UTF8

    # WebSearch is a server-side Anthropic tool: Claude Code sends it as a tool with no
    # input_schema, which vLLM on the Logos worker nodes rejects with 400 and Claude
    # Code then retries in a loop. Denying it keeps it out of the request. A separate
    # settings FILE, so %USERPROFILE%\.claude\settings.json stays untouched.
    '{ "permissions": { "deny": ["WebSearch"] } }' |
        Set-Content -LiteralPath $SettingsFile -Encoding UTF8

    Write-Host 'Installed:'
    Write-Host "  $ShimPath"
    Write-Host "  $InstallPath"
    Write-Host "  $KeyFile (key, readable by you only)"
    Write-Host "  $ConfigFile"
    Write-Host "  $SettingsFile"
    Write-Host ''
    Write-Host 'Nothing else on this machine was modified — plain `claude` still uses your'
    Write-Host 'Anthropic subscription.'
    Write-Host ''

    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    if ($userPath -split ';' -contains $InstallDir) {
        Write-Host 'Run: claude-logos'
    } else {
        Write-Host "$InstallDir is not on your PATH yet. Add it:"
        Write-Host ''
        Write-Host "  `$p = [Environment]::GetEnvironmentVariable('Path','User'); ``"
        Write-Host "  [Environment]::SetEnvironmentVariable('Path', `"`$p;$InstallDir`", 'User')"
        Write-Host ''
        Write-Host 'Then open a new terminal and run: claude-logos'
    }
}

function Protect-UserOnly([string]$Path) {
    # Strip inheritance and leave a single ACE for the current user: the closest
    # equivalent of chmod 600 for a file holding a bearer token.
    try {
        $acl = Get-Acl -LiteralPath $Path
        $acl.SetAccessRuleProtection($true, $false)
        foreach ($rule in @($acl.Access)) { $acl.RemoveAccessRule($rule) | Out-Null }
        $acl.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
            [System.Security.Principal.WindowsIdentity]::GetCurrent().Name,
            'FullControl', 'Allow')))
        Set-Acl -LiteralPath $Path -AclObject $acl
    } catch {
        Write-Note "could not tighten permissions on $Path ($($_.Exception.Message))"
    }
}

# ── -Uninstall ──────────────────────────────────────────────────────────────────
function Invoke-LogosUninstall {
    $removed = $false

    # The AI Tools page used to configure Claude Code by writing an env block into
    # %USERPROFILE%\.claude\settings.json. Leaving it behind would keep pointing plain
    # `claude` at Logos after an uninstall, so offer to clean it — but only when it
    # really is the Logos block.
    $userSettings = Join-Path $env:USERPROFILE '.claude\settings.json'
    if (Test-Path -LiteralPath $userSettings) {
        $managed = @(
            'ANTHROPIC_BASE_URL', 'ANTHROPIC_AUTH_TOKEN', 'ANTHROPIC_API_KEY',
            'ANTHROPIC_MODEL', 'ANTHROPIC_DEFAULT_HAIKU_MODEL',
            'ANTHROPIC_DEFAULT_SONNET_MODEL', 'ANTHROPIC_DEFAULT_OPUS_MODEL',
            'ANTHROPIC_DEFAULT_FABLE_MODEL', 'ANTHROPIC_SMALL_FAST_MODEL',
            'CLAUDE_CODE_MAX_CONTEXT_TOKENS', 'CLAUDE_CODE_MAX_OUTPUT_TOKENS',
            'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC'
        )
        try {
            $cfg = Get-Content -Raw -LiteralPath $userSettings | ConvertFrom-Json
        } catch { $cfg = $null }
        $base = if ($cfg -and $cfg.env) { "$($cfg.env.ANTHROPIC_BASE_URL)".TrimEnd('/') } else { '' }
        # A user who put their own ANTHROPIC_BASE_URL there keeps it.
        $isLogos = $base -and ($base -eq $LogosUrl -or $base.ToLower().Contains('logos'))
        $stale = if ($isLogos) {
            @($managed | Where-Object { $cfg.env.PSObject.Properties.Name -contains $_ })
        } else { @() }
        if ($stale.Count -gt 0) {
            Write-Host "Found an older Logos env block in ${userSettings}:"
            $stale | ForEach-Object { Write-Host "  $_" }
            Write-Host 'It points plain `claude` at Logos, so leaving it keeps the setup half-installed.'
            $doIt = $Yes
            if (-not $doIt) {
                $answer = Read-Host 'Remove those keys? [y/N]'
                $doIt = $answer -match '^[yY]'
            }
            if ($doIt) {
                foreach ($name in $stale) { $cfg.env.PSObject.Properties.Remove($name) }
                if (-not $cfg.env.PSObject.Properties.Name) { $cfg.PSObject.Properties.Remove('env') }
                if ($cfg.permissions -and $cfg.permissions.deny) {
                    $kept = @($cfg.permissions.deny | Where-Object { $_ -ne 'WebSearch' })
                    if ($kept.Count -gt 0) { $cfg.permissions.deny = $kept }
                    else { $cfg.permissions.PSObject.Properties.Remove('deny') }
                    if (-not $cfg.permissions.PSObject.Properties.Name) {
                        $cfg.PSObject.Properties.Remove('permissions')
                    }
                }
                $cfg | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $userSettings
                Write-Host "  cleaned $userSettings"
                $removed = $true
            }
        }
    }

    foreach ($path in @($KeyFile, $SettingsFile, $ConfigFile, $KnownModelsFile,
                        $VersionStateFile, $ShimPath, $InstallPath)) {
        if (Test-Path -LiteralPath $path) {
            Remove-Item -LiteralPath $path -Force
            Write-Host "  removed $path"
            $removed = $true
        }
    }
    # Only when empty: never take a directory the user put other things in.
    foreach ($dir in @($ConfigDir, $InstallDir)) {
        if ((Test-Path -LiteralPath $dir) -and -not (Get-ChildItem -LiteralPath $dir -Force)) {
            Remove-Item -LiteralPath $dir -Force
            Write-Host "  removed $dir"
            $removed = $true
        } elseif (Test-Path -LiteralPath $dir) {
            Write-Note "kept $dir — it still holds files this wrapper did not create"
        }
    }

    if ($removed) {
        Write-Host ''
        Write-Host 'Done. Nothing of claude-logos is left; `claude` is unaffected.'
    } else {
        Write-Host 'Nothing to remove — claude-logos is not installed here.'
    }
}

if ($Install) { Invoke-LogosInstall $LogosConfig; exit 0 }
if ($Update) { Invoke-LogosUpdate; exit 0 }
if ($Uninstall) { Invoke-LogosUninstall; exit 0 }

# ── Credential ──────────────────────────────────────────────────────────────────
if (-not (Test-Path -LiteralPath $KeyFile)) {
    Stop-WithError "no key at $KeyFile. Install from the Logos web UI (AI Tools -> Claude Code)."
}
$LogosKey = (Get-Content -Raw -LiteralPath $KeyFile).Trim()
if (-not $LogosKey) { Stop-WithError "the key file $KeyFile is empty" }
if (-not $LogosModel) {
    Stop-WithError "no model configured. Set LOGOS_MODEL in $ConfigFile, or per invocation."
}

# ── Context window, from the gateway ────────────────────────────────────────────
# The window is a property of the lane serving the model, not of the model: the
# capacity planner gives a lane as much context as the node's free KV cache allows, so
# the same model can run at 262144 tokens on one worker and a fraction of that on
# another, and a re-calibration moves it again. One cheap metadata call at startup is
# the only way to be right about a number that moves on its own.
function Get-Window($value) {
    $parsed = 0
    if ([int]::TryParse("$value", [ref]$parsed) -and $parsed -gt 0) { return $parsed }
    return 0
}

$ContextGuaranteed = 0; $ContextAvailable = 0; $ContextMax = 0
$ContextTokens = 0; $ContextOrigin = 'estimate'; $KnownModelIds = @()
$AllModelIds = @()
try {
    $headers = @{ Authorization = "Bearer $LogosKey" }
    $listing = Invoke-RestMethod -Uri "$LogosUrl/v1/models" -Headers $headers -TimeoutSec 15
    $served = $listing.data | Where-Object { $_.id -eq $LogosModel } | Select-Object -First 1
    if ($served) {
        # max_model_len is the size that always holds and the field vLLM itself uses;
        # the *_current_* and *_overall* names are Logos extensions. Older Logos
        # versions send only the first, so every step falls back to the one below it.
        $ContextGuaranteed = Get-Window $served.max_model_len_current_min
        if ($ContextGuaranteed -le 0) { $ContextGuaranteed = Get-Window $served.max_model_len }
        $ContextAvailable = Get-Window $served.max_model_len_current_max
        if ($ContextAvailable -le 0) { $ContextAvailable = $ContextGuaranteed }
        $ContextMax = Get-Window $served.max_model_len_overall
        if ($ContextMax -le 0) { $ContextMax = $ContextAvailable }
        $ContextTokens = switch ($ContextSource) {
            'guaranteed' { $ContextGuaranteed }
            'max' { $ContextMax }
            default { $ContextAvailable }
        }
        if ($ContextTokens -le 0) { $ContextTokens = $ContextGuaranteed }
        if ($ContextTokens -gt 0) { $ContextOrigin = $ContextSource }
        # Nothing is serving the model right now: the current_* pair only exists
        # while a lane is up, so both are empty and the cascade above has nothing
        # to hand back. max_model_len_overall comes from the model profile instead
        # and survives that, so it is still known — and it beats the blind fallback
        # constant, which is a guess for every model at once and is wrong in both
        # directions (way under a 262144-token model, way over a 32768-token one).
        if ($ContextTokens -le 0 -and $ContextMax -gt 0) {
            $ContextTokens = $ContextMax
            $ContextOrigin = 'cold'
        }
    } else {
        $KnownModelIds = @($listing.data | ForEach-Object { $_.id })
    }
    $AllModelIds = @($listing.data | ForEach-Object { $_.id } | Where-Object { $_ })
} catch {
    Write-Note "could not ask Logos how much context is available ($($_.Exception.Message))"
}
if ($ContextTokens -le 0) { $ContextTokens = $ContextFallback; $ContextOrigin = 'estimate' }

$Headroom = [int](Get-Setting 'LOGOS_CONTEXT_HEADROOM' 0)
if ($Headroom -le 0) {
    # ~2% of the window, clamped: enough to absorb tokenizer drift without eating a
    # small window alive.
    $Headroom = [Math]::Min(8192, [Math]::Max(1024, [int]($ContextTokens / 50)))
}
# The number handed to Claude Code is the window MINUS the headroom and nothing else.
# Claude Code subtracts its own output reservation — min(CLAUDE_CODE_MAX_OUTPUT_TOKENS,
# 20000) — from whatever it is told, and then compacts 13000 tokens below that.
# Subtracting the output reservation here as well double-counts it and throws away
# 20000 tokens of context for nothing.
$ContextForCli = $ContextTokens - $Headroom
$CompactAt = $ContextForCli - $MaxOutputTokens - 13000
$HardStopAt = $ContextForCli - $MaxOutputTokens - 3000

# ── Is there room for a session at all? ─────────────────────────────────────────
# Claude Code's opening prompt — its system prompt plus the schemas of every tool
# it carries — is around 13000 tokens before the user has typed anything, and none
# of it is compactable. Since the output reservation is charged against the same
# window, a narrow window can leave less input room than that, and then the FIRST
# request of the session comes back as "maximum context length is 32768 tokens.
# However, you requested 20000 output tokens and your prompt contains at least
# 12769 input tokens" — with nothing to compact yet, and so no way back. The check
# that used to sit here only caught the arithmetic going negative, which a
# 32768-token window passes comfortably while being unusable.
#
# Recorded rather than acted on immediately: -Check exists to diagnose exactly
# this, so it prints the arithmetic and only a real start refuses to run.
$ClaudeCodeBasePromptTokens = 13000
$ContextTooSmall = $HardStopAt -lt $ClaudeCodeBasePromptTokens
# What the reservation would have to be for the opening prompt to fit — measured
# against the auto-compact point (13000) rather than the hard stop (3000), because
# a value that only clears the hard stop leaves auto-compaction firing on every
# turn. Offered only when what is left is still a usable reply length.
$AffordableOutputTokens = $ContextTokens - $Headroom - 13000 - $ClaudeCodeBasePromptTokens

# ── New models since the last run ───────────────────────────────────────────────
# Models get added to a team without anyone telling the people on it, and the
# terminal someone is about to work in is the one place they will read it. First
# run records the baseline silently instead of announcing everything as new.
function Report-NewModels([string[]]$Current) {
    if (-not $Current -or $Current.Count -eq 0) { return }
    if (-not (Test-Path -LiteralPath $KnownModelsFile)) {
        Set-Content -LiteralPath $KnownModelsFile -Value $Current -Encoding UTF8
        return
    }
    $previous = @(Get-Content -LiteralPath $KnownModelsFile)
    $added = @($Current | Where-Object { $previous -notcontains $_ })
    if ($added.Count -gt 0) {
        Write-Host ("new      : {0} now available to you" -f ($added -join ' '))
        Write-Host '           (set $env:LOGOS_MODEL to use one, or re-run the setup on the Logos web UI)'
    }
    Set-Content -LiteralPath $KnownModelsFile -Value $Current -Encoding UTF8
}

# ── Warm-up ─────────────────────────────────────────────────────────────────────
# A session starts, the developer reads the startup line, and the first real
# request lands seconds later — paying for a cold load that could have happened
# during those seconds. This tells Logos the model is about to be used and
# returns immediately; no request is ever sent on the caller's behalf.
function Invoke-Warmup {
    try {
        Invoke-RestMethod -Method Post -TimeoutSec 5 `
            -Uri "$LogosUrl/v1/models/$LogosModel/warmup" `
            -Headers @{ Authorization = "Bearer $LogosKey" } | Out-Null
    } catch {
        # Best-effort: a failed warm-up only means the first request pays for
        # the load itself.
    }
}

function Write-ContextReport {
    Write-Host ("model    : {0}" -f $LogosModel)
    Write-Host ("logos    : {0}" -f $LogosUrl)
    if ($ContextOrigin -eq 'estimate') {
        Write-Host ("context  : {0:N0} tokens (an estimate — Logos reports no size for this model)" -f $ContextTokens)
    } elseif ($ContextOrigin -eq 'cold') {
        Write-Host ("context  : {0:N0} tokens, the maximum this model is served with" -f $ContextTokens)
        Write-Host '           (no lane is up yet, so Logos reports no current size. The first request'
        Write-Host '            brings one up, and how wide it comes up is decided then from whatever'
        Write-Host '            capacity is free — it can land well below this number, in which case'
        Write-Host '            that request is turned down and the next start sizes itself correctly)'
    } else {
        Write-Host ("context  : {0:N0} tokens, using ""{1}"" of what Logos offers" -f $ContextTokens, $ContextOrigin)
        Write-Host ("           (guaranteed {0:N0} / available now {1:N0} / model max {2:N0})" -f `
            $ContextGuaranteed, $ContextAvailable, $ContextMax)
    }
    Write-Host ("session  : compacts itself at ~{0:N0} tokens, stops accepting at ~{1:N0}" -f $CompactAt, $HardStopAt)
    Write-Host ("           ({0:N0} given to Claude Code, {1:N0} kept as a margin, {2:N0} reserved for replies)" -f `
        $ContextForCli, $Headroom, $MaxOutputTokens)
    if ($KnownModelIds.Count -gt 0) {
        Write-Host ("warning  : {0} is not served here. Known models: {1}" -f $LogosModel, ($KnownModelIds -join ' '))
    }
    if ($ContextTooSmall) {
        Write-Host 'BLOCKED  : this window cannot host a Claude Code session.'
        Write-Host ("           {0:N0} tokens of input are left after the {1:N0} reserved for replies and" -f `
            $HardStopAt, $MaxOutputTokens)
        Write-Host ("           the {0:N0} of headroom, and Claude Code needs about {1:N0} of that for its own" -f `
            $Headroom, $ClaudeCodeBasePromptTokens)
        Write-Host '           system prompt and tool definitions — so the first request is rejected.'
        if ($AffordableOutputTokens -ge 4096) {
            Write-Host '           Reserving less fits, at the cost of reply length:'
            Write-Host ("             `$env:LOGOS_MAX_OUTPUT_TOKENS={0}; claude-logos" -f $AffordableOutputTokens)
        }
        Write-Host ("           Otherwise pick a model Logos serves with a wider window (at least {0:N0});" -f `
            ($ClaudeCodeBasePromptTokens + 20000 + 3000 + 1024))
        Write-Host '           the AI Tools page shows what each one gets.'
    } elseif ($CompactAt -lt $ClaudeCodeBasePromptTokens) {
        Write-Host 'warning  : this window is workable but tight — auto-compaction starts almost'
        Write-Host ("           immediately, because {0:N0} tokens are left before it fires and the system" -f $CompactAt)
        Write-Host ("           prompt and tools already take about {0:N0}." -f $ClaudeCodeBasePromptTokens)
    }
    if ($LogosModel -like 'claude-*' -or $LogosModel -like '*[[]1m[]]*') {
        Write-Host 'warning  : Claude Code resolves this id to one of its own models and ignores'
        Write-Host '           CLAUDE_CODE_MAX_CONTEXT_TOKENS for it, so the window above will not'
        Write-Host '           be enforced. Pick a model whose id does not start with "claude-" or'
        Write-Host '           contain "[1m]", or set DISABLE_COMPACT=1 to force the window through'
        Write-Host '           (which turns auto-compaction off).'
    }
}

# ── Claude Code → Logos wiring ──────────────────────────────────────────────────
# $env: assignments live on THIS process only. Nothing is written to a PowerShell
# profile, to the User/Machine environment or to %USERPROFILE%\.claude\settings.json,
# which is what keeps a plain `claude` on your Anthropic subscription.
#
# ANTHROPIC_AUTH_TOKEN sends the key as "Authorization: Bearer", which is what the Logos
# orchestrator reads. ANTHROPIC_API_KEY would use x-api-key instead, so it is cleared to
# avoid an auth-source conflict with any globally set value.
$env:ANTHROPIC_BASE_URL = $LogosUrl
$env:ANTHROPIC_AUTH_TOKEN = $LogosKey
$env:ANTHROPIC_API_KEY = ''
foreach ($slot in @('ANTHROPIC_MODEL', 'ANTHROPIC_DEFAULT_HAIKU_MODEL',
                    'ANTHROPIC_DEFAULT_SONNET_MODEL', 'ANTHROPIC_DEFAULT_OPUS_MODEL',
                    'ANTHROPIC_DEFAULT_FABLE_MODEL', 'ANTHROPIC_SMALL_FAST_MODEL')) {
    Set-Item -Path "env:$slot" -Value $LogosModel
}
$env:CLAUDE_CODE_MAX_CONTEXT_TOKENS = "$ContextForCli"
$env:CLAUDE_CODE_MAX_OUTPUT_TOKENS = "$MaxOutputTokens"
# Keep telemetry, model discovery and other non-inference calls off api.anthropic.com.
$env:CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC = '1'

# Everything the startup line prints, plus which key and effort are in play. It
# deliberately makes no inference request: reading the model list already proves
# the URL, the key and that Logos serves this model.
if ($Check) {
    Write-ContextReport
    Write-Host ("key      : {0} ({1} chars)" -f $KeyFile, $LogosKey.Length)
    Write-Host ("effort   : {0}" -f $(if ($Effort) { $Effort } else { '<not set by this wrapper>' }))
    Report-NewModels $AllModelIds
    Report-NewRevision
    Update-CachedRevision
    exit 0
}

# ── Launch ──────────────────────────────────────────────────────────────────────
# A window too narrow for the opening prompt is refused here rather than handed to
# Claude Code, whose first request would come back as a 400 from the worker that
# reads like a bug in Logos. The report says what is left and how to get around
# it, and -Check above still prints all of it without refusing anything.
if ($ContextTooSmall) {
    Write-ContextReport
    Stop-WithError 'refusing to start: see BLOCKED above'
}

if (-not (Get-Command claude -ErrorAction SilentlyContinue)) {
    Stop-WithError 'claude is not on your PATH — install Claude Code first'
}

# Ask Logos to get the model ready before handing over. The endpoint answers
# immediately (it records a hint rather than doing the work inline), so this is a
# round trip and not a wait — no background job needed, and a failure changes
# nothing except that the first request pays for the load itself.
Invoke-Warmup

# Say how much room this session got. It changes between runs without anything the
# user having changed, so printing it is the difference between "Claude Code
# compacted early again" and "there was less room today".
Write-ContextReport
Report-NewModels $AllModelIds
Report-NewRevision
Update-CachedRevision
Write-Host ''

$passThrough = @()
if (Test-Path -LiteralPath $SettingsFile) { $passThrough += @('--settings', $SettingsFile) }
$forwarded = @($ClaudeArgs | Where-Object { $null -ne $_ })
# Skip our default when an --effort was passed on the command line, so it stays
# overridable per invocation instead of being silently doubled up.
if ($Effort -and -not ($forwarded | Where-Object { $_ -eq '--effort' -or $_ -like '--effort=*' })) {
    $passThrough += @('--effort', $Effort)
}

& claude @passThrough @forwarded
exit $LASTEXITCODE
