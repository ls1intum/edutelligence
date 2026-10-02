import { TestBed } from '@angular/core/testing';

import { MyKeysService } from '../../core/services/my-keys.service';
import { MyKey, ModelAccess } from '../../shared/models/my-key.model';
import {
  AiTools,
  CLAUDE_CODE_CONTEXT_COMFORTABLE,
  CLAUDE_CODE_CONTEXT_FLOOR,
  claudeCodeFitFor,
  servedContextFloorFor,
} from './ai-tools';

/**
 * Claude Code cannot run in an arbitrarily small context window, and the size
 * it needs is arithmetic rather than taste: it reserves 20,000 tokens for a
 * reply on every request whatever it is told, vLLM charges input and output
 * against the same window, and its own system prompt plus tool definitions is
 * ~13,000 tokens before the user has typed anything.
 *
 * A 32,768-token model therefore leaves 12,768 tokens of input — one token
 * short of that opening prompt — and a freshly installed wrapper answered its
 * first message with "maximum context length is 32768 tokens ... you requested
 * 20000 output tokens and your prompt contains at least 12769 input tokens".
 * Nothing in the session recovers from that, so the page must not hand out an
 * install command for such a model in the first place.
 */

const model = (overrides: Partial<ModelAccess> = {}): ModelAccess => ({
  model_name: 'a-model',
  provider_type: 'logosnode',
  context_window_current_min: 262144,
  context_window_current_max: 262144,
  context_window_overall: 262144,
  ...overrides,
});

const KEY: MyKey = {
  id: 1,
  name: 'a key',
  key_value: 'logos-key',
  key_type: 'user',
  environment: 'production',
  log: 'BILLING',
  use_custom_permissions: false,
  used_micro_cents: 0,
  settings: null,
  last_used_at: null,
  rate_limit_usage: null,
  team: {
    id: 1,
    name: 'a team',
    team_monthly_budget_micro_cents: null,
    budget_used_micro_cents: 0,
  },
};

class FakeMyKeysService {
  models: ModelAccess[] = [];

  async getMyKeys(): Promise<MyKey[]> {
    return [KEY];
  }

  async getKeyModels(): Promise<ModelAccess[]> {
    return this.models;
  }
}

describe('the window Claude Code needs', () => {
  it('puts the floor above the reply reservation plus the opening prompt', () => {
    // 13000 opening prompt + 20000 reservation + 3000 hard stop + 1024 headroom.
    expect(CLAUDE_CODE_CONTEXT_FLOOR).toBe(37024);
    // The same, with the 13000-token auto-compact distance instead of the
    // 3000-token hard stop.
    expect(CLAUDE_CODE_CONTEXT_COMFORTABLE).toBe(47024);
  });

  it('rejects the window that produced the report', () => {
    expect(claudeCodeFitFor(model({ context_window_current_min: 32768 }))).toBe('unusable');
  });

  it('accepts a window with room to work', () => {
    // 61440: hard stop at 37212 against a real input cap of 41440, and 27212
    // tokens before auto-compaction — the first window above both thresholds
    // that a worker actually serves.
    expect(claudeCodeFitFor(model({ context_window_current_min: 61440 }))).toBe('ok');
  });

  it('calls a window that starts but compacts at once tight rather than unusable', () => {
    expect(claudeCodeFitFor(model({ context_window_current_min: 40000 }))).toBe('tight');
  });

  it('judges the narrowest reported window, not the widest', () => {
    // The wrapper defaults to "available", but a request may land on any
    // deployment, so the floor is what has to fit.
    const narrowLaneWideModel = model({
      context_window_current_min: 32768,
      context_window_current_max: 32768,
      context_window_overall: 262144,
    });
    expect(servedContextFloorFor(narrowLaneWideModel)).toBe(32768);
    expect(claudeCodeFitFor(narrowLaneWideModel)).toBe('unusable');
  });

  it('never judges a model no lane is serving', () => {
    // Only the profile maximum is known. That is missing information about the
    // window a lane would come up with, not evidence of a narrow one.
    const cold = model({
      context_window_current_min: null,
      context_window_current_max: null,
      context_window_overall: 262144,
    });
    expect(claudeCodeFitFor(cold)).toBe('ok');

    const unknown = model({
      context_window_current_min: null,
      context_window_current_max: null,
      context_window_overall: null,
    });
    expect(claudeCodeFitFor(unknown)).toBe('unknown');
  });
});

describe('AiTools model gating', () => {
  let service: FakeMyKeysService;
  let component: AiTools;

  const build = async (models: ModelAccess[]): Promise<void> => {
    service = new FakeMyKeysService();
    service.models = models;
    await TestBed.configureTestingModule({
      imports: [AiTools],
      providers: [{ provide: MyKeysService, useValue: service }],
    }).compileComponents();
    const fixture = TestBed.createComponent(AiTools);
    component = fixture.componentInstance;
    // ngOnInit pre-selects the key and loads its models; every test starts from
    // the state that leaves behind.
    await component.ngOnInit();
  };

  afterEach(() => TestBed.resetTestingModule());

  it('disables a too-narrow model for Claude Code and says why in the label', async () => {
    await build([model({ model_name: 'narrow', context_window_current_min: 32768 })]);
    component.chooseTool('claudecode');

    // [0] is the blank "Claude Code picks" option; real models follow.
    const option = component.modelOptions()[1];
    expect(option.disabled).toBe(true);
    expect(option.label).toContain('32,768');
    expect(option.label).toContain('too small for Claude Code');
  });

  it('leaves the same model selectable for OpenCode', async () => {
    // OpenCode is told what to reserve, so a narrow window costs it reply
    // length rather than the whole session.
    await build([model({ model_name: 'narrow', context_window_current_min: 32768 })]);
    component.chooseTool('opencode');

    expect(component.modelOptions()[0].disabled).toBe(false);
    expect(component.modelUsable()).toBe(true);
  });

  it('blocks Claude Code setup when the key has no accessible models', async () => {
    await build([]);
    component.chooseTool('claudecode');

    expect(component.modelChosen()).toBe(false);
    expect(component.models().length).toBe(0);
    expect(component.ready()).toBe(false);
    expect(component.canOpen(4)).toBe(false);
  });

  it('lets Claude Code continue without a pin when the only model is too narrow', async () => {
    await build([model({ model_name: 'narrow', context_window_current_min: 32768 })]);
    component.chooseTool('claudecode');

    // No auto-pin: the wrapper lists models and the user picks with /model.
    expect(component.modelChosen()).toBe(false);
    expect(component.canOpen(4)).toBe(true);
    expect(component.ready()).toBe(true);
    // Step 3 stays on screen so the blank vs pin choice is explicit.
    expect(component.isSkipped(3)).toBe(false);
  });

  it('blocks install when a too-narrow model is explicitly pinned for Claude Code', async () => {
    await build([model({ model_name: 'narrow', context_window_current_min: 32768 })]);
    component.chooseTool('claudecode');
    component.selectModel('narrow');

    expect(component.modelChosen()).toBe(true);
    expect(component.modelUsable()).toBe(false);
    expect(component.claudeCodeFit()).toBe('unusable');
    expect(component.canOpen(4)).toBe(false);
    expect(component.ready()).toBe(false);
  });

  it('does not auto-pin a model for Claude Code', async () => {
    await build([
      model({ model_name: 'narrow', context_window_current_min: 32768 }),
      model({ model_name: 'wide', context_window_current_min: 131072 }),
    ]);
    component.chooseTool('claudecode');

    expect(component.selected()).toBeNull();
    expect(component.modelChosen()).toBe(false);
    expect(component.canOpen(4)).toBe(true);
    expect(component.ready()).toBe(true);
  });

  it('moves off a blocked model when the tool is switched to Claude Code', async () => {
    await build([
      model({ model_name: 'narrow', context_window_current_min: 32768 }),
      model({ model_name: 'wide', context_window_current_min: 131072 }),
    ]);
    component.chooseTool('opencode');
    component.selectModel('narrow');
    expect(component.modelUsable()).toBe(true);

    component.chooseTool('claudecode');
    expect(component.selected()?.model_name).toBe('wide');
  });

  it('keeps a wide model usable and never skips the Claude Code model step', async () => {
    await build([model({ model_name: 'wide', context_window_current_min: 131072 })]);
    component.chooseTool('claudecode');
    component.selectModel('wide');

    expect(component.modelOptions()[0].value).toBe('');
    expect(component.modelOptions()[1].disabled).toBe(false);
    expect(component.modelOptions()[1].label).toBe('wide');
    expect(component.claudeCodeFit()).toBe('ok');
    expect(component.isSkipped(3)).toBe(false);
  });
});

describe('the tool comparison', () => {
  const build = async (): Promise<AiTools> => {
    await TestBed.configureTestingModule({
      imports: [AiTools],
      providers: [{ provide: MyKeysService, useValue: new FakeMyKeysService() }],
    }).compileComponents();
    const fixture = TestBed.createComponent(AiTools);
    return fixture.componentInstance;
  };

  afterEach(() => TestBed.resetTestingModule());

  it('lists the features both tools share first, in the same order, in both columns', async () => {
    const component = await build();
    const row = component.comparison.find((r) => r.dimension === 'Agent features');
    expect(row).toBeDefined();

    const features = (cell: string) => cell.split(',').map((f) => f.trim().toLowerCase());
    const claudeCode = features(row!.claudecode);
    const openCode = features(row!.opencode);

    const shared = claudeCode.filter((f) => openCode.includes(f));
    expect(shared).toContain('mcp');
    // The shared features must stand first in each list, in the same order, so
    // the row reads across like the rest of the table rather than as two
    // separate feature lists that happen to sit next to each other.
    expect(claudeCode.slice(0, shared.length)).toEqual(shared);
    expect(openCode.slice(0, shared.length)).toEqual(shared);
  });
});
