import { CdkDragDrop } from '@angular/cdk/drag-drop';
import { TestBed } from '@angular/core/testing';

import { TeamApiKey, TeamDetail } from '../../../../shared/models/team.model';
import { TeamManagementService } from '../../../../core/services/team-management.service';
import { AppKeysTabComponent } from './app-keys-tab';
import { SLA_PRIORITY } from '../key-sla';

/**
 * Reordering application keys.
 *
 * Moving a row does two things at once: it records a display order, and — when
 * the row crosses a tier boundary — it rewrites the key's SLA, which is the
 * part the orchestrator's queue actually reads. A move that changes a tier
 * nobody aimed at silently re-prioritises production traffic, so the rule for
 * which tier a dropped row lands in is worth pinning down.
 */
describe('AppKeysTabComponent reordering', () => {
  const updateApiKey = vi.fn();

  const makeKey = (id: number, priority: number): TeamApiKey => ({
    id,
    name: `key-${id}`,
    key_type: 'application',
    environment: 'prod',
    default_priority: priority,
    monthly_budget_micro_cents: null,
    cloud_rpm_limit: null,
    cloud_tpm_limit: null,
    local_rpm_limit: null,
    local_tpm_limit: null,
  });

  /**
   * One ux-critical row above two ux-high-prio rows — the shape that exposes a
   * wrong tier rule, since the lower of the two ends up directly below the
   * critical row after a same-tier swap. Rebuilt per test: a successful SLA
   * change writes through to the key object.
   */
  function setup(): {
    component: AppKeysTabComponent;
    critical: TeamApiKey;
    highPrioA: TeamApiKey;
    highPrioB: TeamApiKey;
  } {
    const critical = makeKey(1, SLA_PRIORITY['ux-critical']);
    const highPrioA = makeKey(2, SLA_PRIORITY['ux-high-prio']);
    const highPrioB = makeKey(3, SLA_PRIORITY['ux-high-prio']);

    const component = TestBed.runInInjectionContext(() => new AppKeysTabComponent());
    component.canEdit = true;
    component.teamId = 7;
    component.apiKeys = [critical, highPrioA, highPrioB];

    return { component, critical, highPrioA, highPrioB };
  }

  const drop = (previousIndex: number, currentIndex: number) =>
    ({ previousIndex, currentIndex }) as CdkDragDrop<TeamApiKey[]>;

  const ids = (component: AppKeysTabComponent) => component.orderedKeys().map((k) => k.id);

  const memoryStore = new Map<string, string>();

  beforeEach(() => {
    memoryStore.clear();
    vi.stubGlobal('localStorage', {
      getItem: (key: string) => memoryStore.get(key) ?? null,
      setItem: (key: string, value: string) => {
        memoryStore.set(key, value);
      },
      removeItem: (key: string) => {
        memoryStore.delete(key);
      },
      clear: () => memoryStore.clear(),
    });
    vi.clearAllMocks();
    updateApiKey.mockResolvedValue(undefined);
    TestBed.configureTestingModule({
      providers: [{ provide: TeamManagementService, useValue: { updateApiKey } }],
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('sorts by tier first and by the manual order only within a tier', () => {
    const { component, critical, highPrioA, highPrioB } = setup();
    expect(ids(component)).toEqual([critical.id, highPrioA.id, highPrioB.id]);
  });

  it('leaves the tier alone when two rows of the same tier swap', async () => {
    const { component, critical, highPrioA, highPrioB } = setup();
    // Drag highPrioB onto highPrioA's position. The moved row then sits
    // directly below the ux-critical row, which must not promote it: the
    // person reordered two ux-high-prio keys and nothing else.
    await component.onDrop(drop(2, 1));

    expect(component.slaOf(highPrioB)).toBe('ux-high-prio');
    expect(updateApiKey).not.toHaveBeenCalled();
    expect(ids(component)).toEqual([critical.id, highPrioB.id, highPrioA.id]);
  });

  it('adopts the tier of the row a key is dropped onto', async () => {
    const { component, highPrioA } = setup();
    // Dropping a ux-high-prio row onto the ux-critical row takes over its tier.
    await component.onDrop(drop(1, 0));

    expect(component.slaOf(highPrioA)).toBe('ux-critical');
    expect(updateApiKey).toHaveBeenCalledWith(highPrioA.id, {
      default_priority: SLA_PRIORITY['ux-critical'],
    });
  });

  it('lowers a key dragged down onto a weaker tier', async () => {
    const { component, critical } = setup();
    await component.onDrop(drop(0, 2));

    expect(component.slaOf(critical)).toBe('ux-high-prio');
    expect(updateApiKey).toHaveBeenCalledWith(critical.id, {
      default_priority: SLA_PRIORITY['ux-high-prio'],
    });
  });

  it('recomputes the list when the parent replaces the keys', () => {
    const { component, critical } = setup();
    component.apiKeys = [critical];

    expect(ids(component)).toEqual([critical.id]);
  });

  it('ignores a move when the caller may not edit', async () => {
    const { component, critical, highPrioA, highPrioB } = setup();
    component.canEdit = false;
    await component.onDrop(drop(2, 0));

    expect(updateApiKey).not.toHaveBeenCalled();
    expect(ids(component)).toEqual([critical.id, highPrioA.id, highPrioB.id]);
  });

  it('pins the default tier on a key that has no priority of its own', async () => {
    const { component } = setup();
    // An unset key shows as inherited, so picking any of the three tiers —
    // including the effective one — is a real write that stops inheritance.
    const unset = makeKey(4, 0);
    component.apiKeys = [unset];
    component.team = { priority: 10 } as TeamDetail;

    expect(component.isInherited(unset)).toBe(true);
    expect(component.slaOf(unset)).toBe('ux-critical');

    await component.changeSla(unset, 'ux-high-prio');

    expect(updateApiKey).toHaveBeenCalledWith(unset.id, {
      default_priority: SLA_PRIORITY['ux-high-prio'],
    });
    expect(component.isInherited(unset)).toBe(false);
  });

  it('pins ux-critical on an inherited key whose team is already critical', async () => {
    const { component } = setup();
    const unset = makeKey(4, 0);
    component.apiKeys = [unset];
    component.team = { priority: 10 } as TeamDetail;

    await component.changeSla(unset, 'ux-critical');

    expect(updateApiKey).toHaveBeenCalledWith(unset.id, {
      default_priority: SLA_PRIORITY['ux-critical'],
    });
  });

  it('does not write again when the stored priority already matches the tier', async () => {
    const { component, highPrioA } = setup();
    await component.changeSla(highPrioA, 'ux-high-prio');

    expect(updateApiKey).not.toHaveBeenCalled();
  });

  it('restores the previous tier when saving the SLA fails', async () => {
    const { component, highPrioA } = setup();
    updateApiKey.mockRejectedValue(new Error('nope'));

    await component.onDrop(drop(1, 0));

    expect(component.slaOf(highPrioA)).toBe('ux-high-prio');
    expect(component.slaError()).toContain(highPrioA.name);
  });

  it('rejects a second move while an SLA update is still in flight', async () => {
    const { component, highPrioA, highPrioB, critical } = setup();
    let finishSave!: () => void;
    updateApiKey.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          finishSave = resolve;
        }),
    );

    const first = component.onDrop(drop(1, 0)); // highPrioA → critical
    await Promise.resolve();
    expect(component.slaSaving().has(highPrioA.id)).toBe(true);

    await component.onDrop(drop(0, 2)); // attempt to move the saving key again

    expect(ids(component)).toEqual([highPrioA.id, critical.id, highPrioB.id]);
    expect(updateApiKey).toHaveBeenCalledTimes(1);

    finishSave();
    await first;
  });
});
