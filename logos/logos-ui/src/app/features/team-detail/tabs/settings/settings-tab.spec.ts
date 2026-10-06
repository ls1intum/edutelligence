import { TestBed } from '@angular/core/testing';

import { TeamManagementService } from '../../../../core/services/team-management.service';
import { parseProviderCap, SettingsTabComponent } from './settings-tab';

describe('parseProviderCap', () => {
  it('reads blank as no cap', () => {
    expect(parseProviderCap('')).toBeNull();
    expect(parseProviderCap('   ')).toBeNull();
  });

  it('reads a dollar amount as micro-cents', () => {
    expect(parseProviderCap('0')).toBe(0);
    expect(parseProviderCap('12.50')).toBe(1_250_000_000);
    expect(parseProviderCap('12,5')).toBe(1_250_000_000);
  });

  it('rejects anything that is not a complete non-negative amount', () => {
    for (const input of ['abc', '12abc', '-5', '1.2.3', '$5']) {
      expect(parseProviderCap(input)).toBeUndefined();
    }
  });
});

describe('SettingsTabComponent provider budgets', () => {
  const upsertTeamProviderBudget = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    upsertTeamProviderBudget.mockResolvedValue({});
    TestBed.configureTestingModule({
      providers: [
        {
          provide: TeamManagementService,
          useValue: {
            upsertTeamProviderBudget,
            getTeamProviderBudgets: vi.fn().mockResolvedValue([]),
            getAllProviders: vi.fn().mockResolvedValue([]),
          },
        },
      ],
    });
  });

  function create(): SettingsTabComponent {
    const component = TestBed.createComponent(SettingsTabComponent).componentInstance;
    component.teamId = 7;
    component.canEdit = true;
    component.newProviderId.set('3');
    return component;
  }

  it('does not save an invalid cap as unlimited', async () => {
    const component = create();
    component.newProviderBudget.set('abc');

    await component.addProviderBudget();

    expect(upsertTeamProviderBudget).not.toHaveBeenCalled();
    expect(component.providerBudgetError()).toContain('dollar amount');
  });

  it('saves a blank cap as unlimited', async () => {
    const component = create();
    component.newProviderBudget.set('');

    await component.addProviderBudget();

    expect(upsertTeamProviderBudget).toHaveBeenCalledWith(7, 3, null);
  });
});
