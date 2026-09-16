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
});
