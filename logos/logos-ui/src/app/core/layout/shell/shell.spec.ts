import { computed, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { RouterTestingModule } from '@angular/router/testing';

import { AuthService } from '../../auth/services/auth.service';
import { ThemeService } from '../../services/theme.service';
import { MyKeysService } from '../../services/my-keys.service';
import { User, UserRole } from '../../auth/models/user.model';
import { Shell } from './shell';

/**
 * The runner is opt-in per deployment: where its compose profile is not
 * selected there is no /api/agent router at all, and the shell's probe
 * comes back with the SPA's HTML shell instead of the runner's JSON health
 * answer. The menu must follow the runner, not the role — an admin of a
 * deployment without agents would otherwise get an entry that leads to a
 * page that cannot load anything.
 */

const makeUser = (role: UserRole): User => ({
  user_id: 1,
  username: 'operator',
  prename: 'Op',
  name: 'Erator',
  email: 'operator@example.com',
  role,
  teams: [],
});

interface ProbeResponse {
  ok: boolean;
  status: number;
  headers: Headers;
}

/** The runner's health answer: JSON, whatever its sub-status says. */
const runnerAnswer: ProbeResponse = {
  ok: true,
  status: 200,
  headers: new Headers({ 'content-type': 'application/json' }),
};

/**
 * The SPA fallback: no runner means no /api/agent router, so the request
 * falls through to the UI's catch-all, which answers the probe with
 * index.html — a 200 that is not an answer from the runner.
 */
const spaAnswer: ProbeResponse = {
  ok: true,
  status: 200,
  headers: new Headers({ 'content-type': 'text/html; charset=utf-8' }),
};

/** What a runner that is selected but not answering looks like through the proxy. */
const unreachableAnswer: ProbeResponse = {
  ok: false,
  status: 503,
  headers: new Headers(),
};

class FakeAuthService {
  currentUser = signal<User | null>(null);
  role = computed(() => this.currentUser()?.role ?? null);
  logout = vi.fn();
}

describe('Shell', () => {
  let fixture: ComponentFixture<Shell> | undefined;
  let component: Shell;
  let auth: FakeAuthService;
  let fetchSpy: ReturnType<typeof vi.fn>;

  const menuLabels = (): string[] =>
    component.navSections().flatMap((section) => section.items.map((item) => item.label));

  const probeAs = async (response: ProbeResponse): Promise<void> => {
    fetchSpy.mockResolvedValue(response);
    await component.probeAgent();
  };

  beforeEach(async () => {
    fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    auth = new FakeAuthService();

    await TestBed.configureTestingModule({
      imports: [Shell, RouterTestingModule],
      providers: [
        { provide: AuthService, useValue: auth },
        { provide: MyKeysService, useValue: { hasKeys: signal<boolean | null>(null) } },
        { provide: ThemeService, useValue: { isDark: signal(false), toggle: vi.fn() } },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(Shell);
    component = fixture.componentInstance;
  });

  afterEach(() => {
    fixture?.destroy();
    vi.unstubAllGlobals();
  });

  it("probes the runner's public health endpoint when the shell opens", () => {
    expect(fetchSpy).toHaveBeenCalledWith('/api/agent/health', { cache: 'no-store' });
  });

  describe('the agents menu entry', () => {
    it("stays out when the SPA's HTML fallback answers the probe", async () => {
      auth.currentUser.set(makeUser('logos_admin'));
      await probeAs(spaAnswer);

      expect(component.agentAvailable()).toBe(false);
      expect(menuLabels()).not.toContain('Agents');
    });

    it('appears when the runner answers with its JSON health check', async () => {
      auth.currentUser.set(makeUser('logos_admin'));
      await probeAs(runnerAnswer);

      expect(component.agentAvailable()).toBe(true);
      expect(menuLabels()).toContain('Agents');
    });

    it('stays out when the runner is selected but not answering', async () => {
      auth.currentUser.set(makeUser('logos_admin'));
      await probeAs(unreachableAnswer);

      expect(menuLabels()).not.toContain('Agents');
    });

    it('stays out when the probe cannot reach anything at all', async () => {
      auth.currentUser.set(makeUser('logos_admin'));
      fetchSpy.mockRejectedValue(new TypeError('failed to fetch'));
      await component.probeAgent();

      expect(component.agentAvailable()).toBe(false);
      expect(menuLabels()).not.toContain('Agents');
    });

    it('does not appear for a role without it, even with the runner up', async () => {
      auth.currentUser.set(makeUser('app_admin'));
      await probeAs(runnerAnswer);

      expect(menuLabels()).not.toContain('Agents');
    });

    it('keeps the other entries when the agents entry is filtered out', async () => {
      auth.currentUser.set(makeUser('logos_admin'));
      await probeAs(spaAnswer);

      expect(menuLabels()).toEqual(
        expect.arrayContaining([
          'Dashboard',
          'Statistics',
          'Models',
          'Providers',
          'Policies',
          'Billing',
        ]),
      );
    });
  });
});
