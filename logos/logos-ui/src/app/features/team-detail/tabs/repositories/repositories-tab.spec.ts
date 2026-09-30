import { TestBed } from '@angular/core/testing';

import { TeamManagementService } from '../../../../core/services/team-management.service';
import { TeamRepository } from '../../../../shared/models/team.model';
import { RepositoriesTabComponent } from './repositories-tab';

describe('RepositoriesTabComponent', () => {
  const getTeamRepositories = vi.fn();
  const createTeamRepository = vi.fn();
  const updateTeamRepository = vi.fn();
  const deleteTeamRepository = vi.fn();

  const sample: TeamRepository = {
    id: 11,
    team_id: 7,
    repo_url: 'https://github.com/ls1intum/edutelligence.git',
    repo_slug: 'ls1intum/edutelligence',
    branch: 'main',
    paths: ['logos'],
  };

  beforeEach(() => {
    vi.clearAllMocks();
    getTeamRepositories.mockResolvedValue([sample]);
    createTeamRepository.mockResolvedValue(sample);
    updateTeamRepository.mockResolvedValue(sample);
    deleteTeamRepository.mockResolvedValue(undefined);
    TestBed.configureTestingModule({
      providers: [
        {
          provide: TeamManagementService,
          useValue: {
            getTeamRepositories,
            createTeamRepository,
            updateTeamRepository,
            deleteTeamRepository,
          },
        },
      ],
    });
  });

  function setup(): RepositoriesTabComponent {
    const component = TestBed.runInInjectionContext(() => new RepositoriesTabComponent());
    component.teamId = 7;
    component.canEdit = true;
    return component;
  }

  it('loads repositories for the team', async () => {
    const component = setup();
    await component.load();
    expect(getTeamRepositories).toHaveBeenCalledWith(7);
    expect(component.repositories()).toEqual([sample]);
  });

  it('creates a link with parsed path filters', async () => {
    const component = setup();
    component.openCreate();
    component.formUrl.set('https://github.com/ls1intum/Artemis');
    component.formBranch.set('develop');
    component.formPaths.set('src/ai, services/llm');
    await component.submitForm();
    expect(createTeamRepository).toHaveBeenCalledWith(7, {
      repo_url: 'https://github.com/ls1intum/Artemis',
      branch: 'develop',
      paths: ['src/ai', 'services/llm'],
    });
    expect(component.formOpen()).toBe(false);
  });

  it('updates an existing link', async () => {
    const component = setup();
    component.openEdit(sample);
    component.formBranch.set('release');
    component.formPaths.set('');
    await component.submitForm();
    expect(updateTeamRepository).toHaveBeenCalledWith(7, 11, {
      repo_url: sample.repo_url,
      branch: 'release',
      paths: null,
    });
  });

  it('unlinks a repository after confirm', async () => {
    const component = setup();
    component.askDelete(sample);
    await component.confirmDelete();
    expect(deleteTeamRepository).toHaveBeenCalledWith(7, 11);
    expect(component.deleteOpen()).toBe(false);
  });

  it('surfaces API detail on create failure', async () => {
    createTeamRepository.mockRejectedValue({
      error: { detail: 'repo_url must be a GitHub repository URL' },
    });
    const component = setup();
    component.openCreate();
    component.formUrl.set('https://gitlab.com/x/y');
    await component.submitForm();
    expect(component.formError()).toContain('GitHub');
    expect(component.formOpen()).toBe(true);
  });
});
