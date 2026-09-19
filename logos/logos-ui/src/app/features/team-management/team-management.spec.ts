import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';

import { AuthService } from '../../core/auth/services/auth.service';
import { User } from '../../core/auth/models/user.model';
import { TeamManagementService } from '../../core/services/team-management.service';
import { Team } from '../../shared/models/team.model';
import { TeamManagement } from './team-management';

function team(overrides: Partial<Team> = {}): Team {
  return {
    id: 2001,
    name: 'test-team',
    owners: [],
    member_count: 3,
    model_count: 2,
    default_cloud_rpm_limit: 5,
    default_cloud_tpm_limit: 10000,
    default_local_rpm_limit: 5,
    default_local_tpm_limit: 10000,
    priority: null,
    is_caller_owner: true,
    managed: false,
    ...overrides,
  };
}

function user(role: User['role']): User {
  return {
    user_id: 1001,
    username: 'testuser',
    prename: 'Test',
    name: 'User',
    email: 'test@example.com',
    role,
    teams: [],
  };
}

describe('TeamManagement', () => {
  let fixture: ComponentFixture<TeamManagement>;
  let component: TeamManagement;
  let teamService: {
    getTeams: ReturnType<typeof vi.fn>;
    getAdminUsers: ReturnType<typeof vi.fn>;
    updateTeamPriority: ReturnType<typeof vi.fn>;
  };
  let currentUser: ReturnType<typeof signal<User | null>>;

  async function createFor(role: User['role']): Promise<void> {
    currentUser = signal<User | null>(user(role));
    teamService.getTeams.mockResolvedValue([team()]);
    await TestBed.configureTestingModule({
      imports: [TeamManagement],
      providers: [
        { provide: AuthService, useValue: { currentUser } },
        { provide: TeamManagementService, useValue: teamService },
        { provide: Router, useValue: { navigate: vi.fn() } },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(TeamManagement);
    component = fixture.componentInstance;
    fixture.detectChanges();
    // Let ngOnInit's fetchTeams() settle, then re-render with the result.
    await new Promise((resolve) => setTimeout(resolve, 0));
    fixture.detectChanges();
  }

  beforeEach(() => {
    teamService = {
      getTeams: vi.fn().mockResolvedValue([]),
      getAdminUsers: vi.fn().mockResolvedValue([]),
      updateTeamPriority: vi.fn().mockResolvedValue(undefined),
    };
    TestBed.resetTestingModule();
  });

  it('labels the priority values, with Default for unset teams', async () => {
    await createFor('logos_admin');
    expect(component.priorityLabel(team({ priority: null }))).toBe('Default');
    expect(component.priorityLabel(team({ priority: 1 }))).toBe('Low');
    expect(component.priorityLabel(team({ priority: 5 }))).toBe('Normal');
    expect(component.priorityLabel(team({ priority: 10 }))).toBe('High');
    expect(component.priorityLabel(team({ priority: 7 }))).toBe('7');
  });

  it('renders an editable priority select for logos admins', async () => {
    await createFor('logos_admin');
    const select: HTMLSelectElement | null = fixture.nativeElement.querySelector('.priority-cell select');
    expect(select).toBeTruthy();
    if (!select) return;
    expect(select.disabled).toBe(false);
  });

  it('renders the priority read-only for app admins', async () => {
    await createFor('app_admin');
    expect(fixture.nativeElement.querySelector('.priority-cell select')).toBeNull();
    expect(fixture.nativeElement.querySelector('.priority-cell .count-badge')?.textContent).toContain('Default');
  });

  it('saves the selected priority and updates the team', async () => {
    await createFor('logos_admin');

    await component.changeTeamPriority(team(), '10');

    expect(teamService.updateTeamPriority).toHaveBeenCalledWith(2001, 10);
    expect(component.teams()[0].priority).toBe(10);
    expect(component.priorityError()).toBe('');
  });

  it('offers Default plus every priority value 1-10, with bucket annotations', async () => {
    await createFor('logos_admin');
    const select: HTMLSelectElement | null = fixture.nativeElement.querySelector('.priority-cell select');
    expect(select).toBeTruthy();
    if (!select) return;
    const options = Array.from(select.options);
    expect(options.map((o) => o.value)).toEqual(['', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10']);
    expect(options[1].text).toBe('Low (1)');
    expect(options[5].text).toBe('Normal (5)');
    expect(options[10].text).toBe('High (10)');
    // Non-bucket values are offered as-is.
    expect(options[7].text).toBe('7');
  });

  it('saves a non-bucket priority such as 7 from the select', async () => {
    await createFor('logos_admin');
    const select: HTMLSelectElement | null = fixture.nativeElement.querySelector('.priority-cell select');
    expect(select).toBeTruthy();
    if (!select) return;

    select.value = '7';
    select.dispatchEvent(new Event('change'));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(teamService.updateTeamPriority).toHaveBeenCalledWith(2001, 7);
    expect(component.teams()[0].priority).toBe(7);
    expect(component.priorityLabel(component.teams()[0])).toBe('7');
  });

  it('shows the stored priority on a fresh render (page reload), not Default', async () => {
    await createFor('logos_admin');

    // Drop the row, then render a team that already carries a stored priority
    // — the fresh-render path a page reload takes. A [value] binding on the
    // <select> is applied before the <option>s exist, so the browser drops it
    // and the select reverts to the first option (Default); the selection has
    // to be expressed on the <option> instead.
    component.teams.set([]);
    fixture.detectChanges();
    component.teams.set([team({ priority: 7 })]);
    fixture.detectChanges();

    const select: HTMLSelectElement | null = fixture.nativeElement.querySelector('.priority-cell select');
    expect(select).toBeTruthy();
    if (!select) return;
    const selected = Array.from(select.options).find((o) => o.selected);
    expect(selected?.value).toBe('7');
  });

  it('shows the Default option for a team without a stored priority', async () => {
    await createFor('logos_admin');

    component.teams.set([]);
    fixture.detectChanges();
    component.teams.set([team({ priority: null })]);
    fixture.detectChanges();

    const select: HTMLSelectElement | null = fixture.nativeElement.querySelector('.priority-cell select');
    expect(select).toBeTruthy();
    if (!select) return;
    const selected = Array.from(select.options).find((o) => o.selected);
    expect(selected?.value).toBe('');
  });

  it('treats the empty option as unsetting the priority', async () => {
    await createFor('logos_admin');
    component.teams.set([team({ priority: 10 })]);

    await component.changeTeamPriority(team({ priority: 10 }), '');

    expect(teamService.updateTeamPriority).toHaveBeenCalledWith(2001, null);
    expect(component.teams()[0].priority).toBeNull();
  });

  it('rolls back and reports when saving fails', async () => {
    await createFor('logos_admin');
    teamService.updateTeamPriority.mockRejectedValue(new Error('boom'));

    await component.changeTeamPriority(team(), '1');

    expect(component.teams()[0].priority).toBeNull();
    expect(component.priorityError()).toContain('test-team');
  });

  it('tracks overlapping saves per team, keeping each row locked until its own request finishes', async () => {
    await createFor('logos_admin');
    const teamB = team({ id: 2002, name: 'other-team' });
    component.teams.set([team(), teamB]);

    // Team A's save stays in flight; team B resolves immediately.
    let resolveFirst: (value: void) => void;
    const first = new Promise<void>((resolve) => (resolveFirst = resolve));
    teamService.updateTeamPriority.mockImplementation((id: number) =>
      id === 2001 ? first : Promise.resolve(),
    );

    const selects = (): HTMLSelectElement[] =>
      Array.from(fixture.nativeElement.querySelectorAll('.priority-cell select'));

    const saveA = component.changeTeamPriority(component.teams()[0], '10');
    fixture.detectChanges();
    expect(selects()[0].disabled).toBe(true);

    // Starting team B's save must not unlock team A's in-flight selector.
    await component.changeTeamPriority(teamB, '5');
    fixture.detectChanges();
    expect(selects()[0].disabled).toBe(true);
    expect(selects()[1].disabled).toBe(false);

    // Team A unlocks only when its own request settles.
    resolveFirst!();
    await saveA;
    fixture.detectChanges();
    expect(selects()[0].disabled).toBe(false);
  });
});
