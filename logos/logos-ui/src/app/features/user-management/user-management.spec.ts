import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpClient } from '@angular/common/http';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AuthService } from '../../core/auth/services/auth.service';
import { User } from '../../core/auth/models/user.model';
import {
  UserManagementService,
  ImportPreview,
} from '../../core/services/user-management.service';
import { TeamManagementService } from '../../core/services/team-management.service';
import { PlatformUser } from '../../shared/models/platform-user.model';
import { UserManagement } from './user-management';

function platformUser(overrides: Partial<PlatformUser> = {}): PlatformUser {
  return {
    id: 1001,
    username: 'testuser',
    prename: 'Test',
    name: 'User',
    email: 'test@test.com',
    role: 'app_developer',
    teams: [],
    managed: false,
    ...overrides,
  };
}

function admin(): User {
  return {
    user_id: 1002,
    username: 'adminuser',
    prename: 'Admin',
    name: 'User',
    email: 'admin@test.com',
    role: 'logos_admin',
    teams: [],
  };
}

describe('UserManagement CSV import', () => {
  let fixture: ComponentFixture<UserManagement>;
  let component: UserManagement;
  let userSvc: {
    getUsers: ReturnType<typeof vi.fn>;
    previewImport: ReturnType<typeof vi.fn>;
    importUsers: ReturnType<typeof vi.fn>;
  };

  // The parsed shape of the example CSV from the import flow: an extra,
  // irrelevant column (Pass Status) that must be shown but never stored.
  const COLUMNS = ['First Name', 'Last Name', 'Email', 'Matriculation Number', 'Pass Status'];
  const ROWS: string[][] = [
    ['Tobias', 'Wasner', 'tobias.wasner@tum.de', '984734', 'passed'],
    ['Jane', 'Doe', 'jane@example.com', '123456', 'failed'],
  ];

  async function create(): Promise<void> {
    userSvc = {
      getUsers: vi.fn().mockResolvedValue([platformUser()]),
      previewImport: vi.fn(),
      importUsers: vi.fn(),
    };
    const currentUser = signal<User | null>(admin());
    await TestBed.configureTestingModule({
      imports: [UserManagement],
      providers: [
        { provide: AuthService, useValue: { currentUser } },
        { provide: UserManagementService, useValue: userSvc },
        { provide: TeamManagementService, useValue: { getTeams: vi.fn().mockResolvedValue([]) } },
        { provide: HttpClient, useValue: {} },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(UserManagement);
    component = fixture.componentInstance;
    fixture.detectChanges();
    await new Promise((resolve) => setTimeout(resolve, 0));
    fixture.detectChanges();
  }

  function loadPreview(preview: ImportPreview): Promise<void> {
    userSvc.previewImport.mockResolvedValue(preview);
    return (component as unknown as { loadImportPreview: (f: File) => Promise<void> }).loadImportPreview(
      { name: 'people.csv' } as unknown as File,
    );
  }

  beforeEach(() => {
    TestBed.resetTestingModule();
  });

  it('guesses the mapping for common export headers', async () => {
    await create();
    const guess = (component as unknown as { guessMapping: (c: string[]) => object }).guessMapping(COLUMNS);
    expect(guess).toEqual({ prename: '0', name: '1', email: '2' });
  });

  it('populates the preview, selects every row and guesses the mapping', async () => {
    await create();
    await loadPreview({ columns: COLUMNS, rows: ROWS });

    expect(component.importColumns()).toEqual(COLUMNS);
    expect(component.importRows()).toEqual(ROWS);
    expect(component.importMapping()).toEqual({ prename: '0', name: '1', email: '2' });
    expect([...component.importSelected()]).toEqual([0, 1]);
  });

  it('marks a row existing when its mapped email already belongs to a user', async () => {
    await create();
    component.importColumns.set(COLUMNS);
    component.importRows.set([['A', 'B', 'test@test.com', '1', 'passed']]);
    component.importMapping.set({ prename: '0', name: '1', email: '2' });
    component.importSelected.set(new Set([0]));

    expect(component.rowStatus(0)).toBe('existing');
    expect(component.importSummary()).toEqual({ selected: 1, toCreate: 0, existing: 1, total: 1 });
  });

  it('requires all three columns mapped and at least one selected row', async () => {
    await create();
    component.importColumns.set(COLUMNS);
    component.importRows.set(ROWS);
    component.importSelected.set(new Set([0]));

    component.importMapping.set({ prename: '0', name: '1', email: '' });
    expect(component.importValid()).toBe(false);

    component.importMapping.set({ prename: '0', name: '1', email: '2' });
    expect(component.importValid()).toBe(true);

    component.importSelected.set(new Set());
    expect(component.importValid()).toBe(false);
  });

  it('lets the user de-select a row before importing', async () => {
    await create();
    component.importColumns.set(COLUMNS);
    component.importRows.set(ROWS);
    component.importMapping.set({ prename: '0', name: '1', email: '2' });
    component.importSelected.set(new Set([0, 1]));

    component.toggleRow(1);
    expect([...component.importSelected()]).toEqual([0]);

    component.deselectAllRows();
    expect(component.importSelected().size).toBe(0);

    component.selectAllRows();
    expect([...component.importSelected()]).toEqual([0, 1]);
  });

  it('sends only the mapped, selected rows and no team', async () => {
    await create();
    component.importColumns.set(COLUMNS);
    component.importRows.set(ROWS);
    component.importMapping.set({ prename: '0', name: '1', email: '2' });
    // The user de-selects the "failed" student.
    component.importSelected.set(new Set([0]));
    userSvc.importUsers.mockResolvedValue({ summary: { created: 1, existing: 0, failed: 0 }, rows: [] });

    await component.submitImport();

    expect(userSvc.importUsers).toHaveBeenCalledWith([
      { prename: 'Tobias', name: 'Wasner', email: 'tobias.wasner@tum.de' },
    ]);
  });

  it('renders the mapping selects and the full-column preview table', async () => {
    await create();
    component.openImportDialog();
    await loadPreview({ columns: COLUMNS, rows: ROWS });
    fixture.detectChanges();
    // The dialog's content renders into a CDK overlay appended to
    // document.body, outside the fixture's own DOM subtree.
    await fixture.whenStable();

    expect(document.querySelector('#map-prename')).toBeTruthy();
    expect(document.querySelector('#map-name')).toBeTruthy();
    expect(document.querySelector('#map-email')).toBeTruthy();

    // The preview table shows every CSV column, including the irrelevant ones.
    const headers = Array.from(
      document.querySelectorAll('.import-preview-scroll .table-header > div'),
    ).map((d) => d.textContent?.trim());
    expect(headers).toContain('First Name');
    expect(headers).toContain('Matriculation Number');
    expect(headers).toContain('Pass Status');

    // One checkbox per data row.
    expect(document.querySelectorAll('.import-preview-row .import-row-cb').length).toBe(ROWS.length);
  });

  it('floors every preview column at 120px so a wide sheet scrolls instead of squashing', async () => {
    await create();
    component.importColumns.set(['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H']);
    // The 120px floor per column is what the stylesheet's content-width
    // floor on the table card is built around (48px + 120px per column + 96px).
    expect(component.importPreviewGrid()).toBe('48px repeat(8, minmax(120px, 1fr)) 96px');
  });
});

/**
 * The layout contract of the import preview's stylesheet.
 *
 * The unit-test environment applies no layout, so the declarations that keep
 * a wide preview readable are pinned here as text instead.
 */
describe('import preview stylesheet', () => {
  const styles = readStyleSheet();

  it('lets a wide preview scroll sideways instead of clipping its columns', () => {
    const block = ruleBlock(styles, '.import-preview-scroll');
    // .table-card belongs to the data table component, so the floor has to
    // reach it through ::ng-deep.
    expect(block).toMatch(/::ng-deep\s+\.table-card/);
    expect(block).toMatch(/min-width:\s*fit-content/);
  });

  it('keeps the floating Include checkbox clear of the row content on mobile', () => {
    const mobile = ruleBlock(styles, '@media (max-width: 768px)');
    // The data table reserves 44px at the top of a mobile row for the control
    // that floats into the card corner; the preview row's checkbox floats
    // there, so it must keep the reservation instead of the 12px top padding
    // the main table's rows use.
    expect(mobile).toMatch(/\.table-row:not\(\.import-preview-row\)\s*\{\s*padding-top:\s*12px/);
    expect(mobile).not.toMatch(/\.table-row\s*\{\s*padding-top:/);
  });
});

/**
 * Reads the component's stylesheet from the spec's directory as raw text. The
 * unit-test builder's pipeline cannot resolve `?raw` imports, and the
 * environment applies no layout — the specs pin CSS declarations as text
 * instead.
 */
function readStyleSheet(): string {
  return readFileSync(join(dirname(fileURLToPath(import.meta.url)), 'user-management.scss'), 'utf8');
}

/**
 * The full text of a rule, nested rules included: from the opening brace to
 * the matching closing one, so an `@media` block stays whole for the
 * assertions above.
 */
function ruleBlock(source: string, selector: string): string {
  const start = source.indexOf(selector);
  expect(start).toBeGreaterThanOrEqual(0);
  const open = source.indexOf('{', start);
  expect(open).toBeGreaterThan(start);
  let depth = 0;
  for (let i = open; i < source.length; i++) {
    if (source.charAt(i) === '{') depth++;
    if (source.charAt(i) === '}') {
      depth--;
      if (depth === 0) return source.slice(open, i + 1);
    }
  }
  throw new Error(`Unbalanced rule for ${selector}`);
}
