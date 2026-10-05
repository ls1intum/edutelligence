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
});
