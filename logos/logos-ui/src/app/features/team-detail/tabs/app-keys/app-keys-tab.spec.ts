import { CdkDragDrop } from '@angular/cdk/drag-drop';
import { TestBed } from '@angular/core/testing';

import { TeamApiKey } from '../../../../shared/models/team.model';
import { TeamManagementService } from '../../../../core/services/team-management.service';
import { AppKeysTabComponent } from './app-keys-tab';
import { SLA_PRIORITY } from './key-sla';

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
  let updateApiKey: jasmine.Spy;

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
   * A high row above two mediums — the shape that exposes a wrong tier rule,
   * since the second medium ends up directly below the high row after a
   * same-tier swap. Rebuilt per test: a successful SLA change writes through
   * to the key object.
   */
  function setup(): {
    component: AppKeysTabComponent;
    high: TeamApiKey;
    mediumA: TeamApiKey;
    mediumB: TeamApiKey;
  } {
    const high = makeKey(1, SLA_PRIORITY.high);
    const mediumA = makeKey(2, SLA_PRIORITY.medium);
    const mediumB = makeKey(3, SLA_PRIORITY.medium);

    const component = TestBed.runInInjectionContext(() => new AppKeysTabComponent());
    component.canEdit = true;
    component.teamId = 7;
    component.apiKeys = [high, mediumA, mediumB];

    return { component, high, mediumA, mediumB };
  }

  const drop = (previousIndex: number, currentIndex: number) =>
    ({ previousIndex, currentIndex }) as CdkDragDrop<TeamApiKey[]>;

  const ids = (component: AppKeysTabComponent) => component.orderedKeys().map((k) => k.id);

  beforeEach(() => {
    localStorage.clear();
    updateApiKey = jasmine.createSpy('updateApiKey').and.returnValue(Promise.resolve());
    TestBed.configureTestingModule({
      providers: [{ provide: TeamManagementService, useValue: { updateApiKey } }],
    });
  });

  afterEach(() => localStorage.clear());

  it('sorts by tier first and by the manual order only within a tier', () => {
    const { component, high, mediumA, mediumB } = setup();
    expect(ids(component)).toEqual([high.id, mediumA.id, mediumB.id]);
  });

  it('leaves the tier alone when two rows of the same tier swap', async () => {
    const { component, high, mediumA, mediumB } = setup();
    // Drag mediumB onto mediumA's position. The moved row then sits directly
    // below the high row, which must not promote it: the person reordered two
    // mediums and nothing else.
    await component.onDrop(drop(2, 1));

    expect(component.slaOf(mediumB)).toBe('medium');
    expect(updateApiKey).not.toHaveBeenCalled();
    expect(ids(component)).toEqual([high.id, mediumB.id, mediumA.id]);
  });

  it('adopts the tier of the row a key is dropped onto', async () => {
    const { component, mediumA } = setup();
    await component.onDrop(drop(1, 0));

    expect(component.slaOf(mediumA)).toBe('high');
    expect(updateApiKey).toHaveBeenCalledWith(mediumA.id, {
      default_priority: SLA_PRIORITY.high,
    });
  });

  it('lowers a key dragged down onto a weaker tier', async () => {
    const { component, high } = setup();
    await component.onDrop(drop(0, 2));

    expect(component.slaOf(high)).toBe('medium');
    expect(updateApiKey).toHaveBeenCalledWith(high.id, {
      default_priority: SLA_PRIORITY.medium,
    });
  });

  it('recomputes the list when the parent replaces the keys', () => {
    const { component, high } = setup();
    component.apiKeys = [high];

    expect(ids(component)).toEqual([high.id]);
  });

  it('ignores a move when the caller may not edit', async () => {
    const { component, high, mediumA, mediumB } = setup();
    component.canEdit = false;
    await component.onDrop(drop(2, 0));

    expect(updateApiKey).not.toHaveBeenCalled();
    expect(ids(component)).toEqual([high.id, mediumA.id, mediumB.id]);
  });

  it('restores the previous tier when saving the SLA fails', async () => {
    const { component, mediumA } = setup();
    updateApiKey.and.returnValue(Promise.reject(new Error('nope')));

    await component.onDrop(drop(1, 0));

    expect(component.slaOf(mediumA)).toBe('medium');
    expect(component.slaError()).toContain(mediumA.name);
  });
});
