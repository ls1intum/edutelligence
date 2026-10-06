import { TestBed } from '@angular/core/testing';

import { TeamManagementService } from '../../../../core/services/team-management.service';
import { TeamDetail } from '../../../../shared/models/team.model';
import { SettingsTabComponent } from './settings-tab';

describe('SettingsTabComponent — Keycloak link', () => {
  const updateTeamKeycloakGroup = vi.fn();
  const getKeycloakGroups = vi.fn();

  function teamDetail(overrides: Partial<TeamDetail> = {}): TeamDetail {
    return {
      id: 7,
      name: 'iOS',
      is_caller_owner: true,
      team_monthly_budget_micro_cents: null,
      budget_used_micro_cents: 0,
      default_monthly_budget_micro_cents: null,
      default_cloud_rpm_limit: 5,
      default_cloud_tpm_limit: 10000,
      default_local_rpm_limit: 5,
      default_local_tpm_limit: 10000,
      priority: null,
      managed: false,
      keycloak_group: null,
      ...overrides,
    };
  }

  beforeEach(() => {
    vi.clearAllMocks();
    updateTeamKeycloakGroup.mockResolvedValue(undefined);
    getKeycloakGroups.mockResolvedValue({ available: false, groups: [] });
    TestBed.configureTestingModule({
      providers: [
        {
          provide: TeamManagementService,
          useValue: {
            updateTeamKeycloakGroup,
            getKeycloakGroups,
            updateTeamLimits: vi.fn(),
            deleteTeam: vi.fn(),
          },
        },
      ],
    });
  });

  function setup(team: TeamDetail, canLinkKeycloak = true): SettingsTabComponent {
    const component = TestBed.runInInjectionContext(() => new SettingsTabComponent());
    component.teamId = team.id;
    component.team = team;
    component.canEdit = true;
    component.canLinkKeycloak = canLinkKeycloak;
    component.ngOnChanges();
    return component;
  }

  it('shows the link the team already holds', () => {
    const component = setup(teamDetail({ managed: true, keycloak_group: 'ios-26ws' }));
    expect(component.keycloakGroup()).toBe('ios-26ws');
    expect(component.linkChanged()).toBe(false);
  });

  it('saves a typed group, trimmed', async () => {
    const component = setup(teamDetail());
    component.keycloakGroup.set('  ios-26ws ');

    await component.saveKeycloakLink();

    expect(updateTeamKeycloakGroup).toHaveBeenCalledWith(7, 'ios-26ws');
  });

  it('sends null when the field is cleared, which unlinks the team', async () => {
    const component = setup(teamDetail({ managed: true, keycloak_group: 'ios-26ws' }));
    component.keycloakGroup.set('');

    await component.saveKeycloakLink();

    expect(updateTeamKeycloakGroup).toHaveBeenCalledWith(7, null);
  });

  // An unlinked team has nothing to remove, so the button must not offer it.
  it('labels the button Save Link until a stored link is cleared', () => {
    const unlinked = setup(teamDetail());
    expect(unlinked.linkButtonLabel()).toBe('Save Link');
    unlinked.keycloakGroup.set('ios-26ws');
    expect(unlinked.linkButtonLabel()).toBe('Save Link');

    const linked = setup(teamDetail({ managed: true, keycloak_group: 'ios-26ws' }));
    expect(linked.linkButtonLabel()).toBe('Save Link');
    linked.keycloakGroup.set('');
    expect(linked.linkButtonLabel()).toBe('Remove Link');
  });

  it('does not save while the field still shows the stored link', async () => {
    const component = setup(teamDetail({ managed: true, keycloak_group: 'ios-26ws' }));

    await component.saveKeycloakLink();

    expect(updateTeamKeycloakGroup).not.toHaveBeenCalled();
  });

  // A rejected group (reserved, already linked) is the one case where the
  // server's own wording says what to fix, so it has to reach the tab.
  it('reports the rejection the server sent', async () => {
    const component = setup(teamDetail());
    updateTeamKeycloakGroup.mockRejectedValue({
      error: { detail: "Keycloak group 'ios-26ws' is already linked to team 'iOS'." },
    });
    component.keycloakGroup.set('ios-26ws');

    await component.saveKeycloakLink();

    expect(component.linkError()).toContain("already linked to team 'iOS'");
  });

  it('suggests only the groups no other team holds', async () => {
    getKeycloakGroups.mockResolvedValue({
      available: true,
      groups: [
        { name: 'ios-26ws', source: 'group', linked_team_id: null, linked_team_name: null },
        { name: 'own', source: 'group', linked_team_id: 7, linked_team_name: 'iOS' },
        { name: 'taken', source: 'role', linked_team_id: 9, linked_team_name: 'other' },
      ],
    });
    const component = setup(teamDetail());
    await Promise.resolve();

    expect(component.availableKeycloakGroups().map((g) => g.name)).toEqual(['ios-26ws', 'own']);
  });

  it('offers no suggestions when the deployment has no directory access', async () => {
    const component = setup(teamDetail());
    await Promise.resolve();

    expect(component.availableKeycloakGroups()).toEqual([]);
  });

  // A datalist has no affordance of its own, so the hint is the only thing
  // telling the admin whether the realm can be browsed at all.
  it('says how many groups can be picked when the realm is readable', async () => {
    getKeycloakGroups.mockResolvedValue({
      available: true,
      groups: [
        { name: 'ios-26ws', source: 'group', linked_team_id: null, linked_team_name: null },
        { name: 'taken', source: 'role', linked_team_id: 9, linked_team_name: 'other' },
      ],
    });
    const component = setup(teamDetail());
    await Promise.resolve();

    expect(component.groupPickerHint()).toContain('1 selectable');
  });

  it('tells the admin to type the claim name when the realm is unreadable', async () => {
    const component = setup(teamDetail());
    await Promise.resolve();

    expect(component.groupPickerHint()).toContain('login claim');
  });

  it('asks for no group directory when the caller may not link one', async () => {
    setup(teamDetail(), false);
    await Promise.resolve();

    expect(getKeycloakGroups).not.toHaveBeenCalled();
  });
});
