import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { ModelRequests } from './model-requests';
import { ModelRequest, ModelRequestService } from '../../core/services/model-request.service';
import { AuthService } from '../../core/auth/services/auth.service';

const makeRequest = (overrides: Partial<ModelRequest> = {}): ModelRequest => ({
  id: 1,
  name: 'gpt-5',
  request_count: 1,
  has_voted: false,
  is_gated: null,
  first_requesting_team: null,
  ...overrides,
});

const makeUser = (teams: { id: number; name: string }[]) => ({
  user_id: 1,
  username: 'testuser',
  prename: 'Test',
  name: 'User',
  email: 'test@test.com',
  role: 'app_developer',
  teams,
});

describe('ModelRequests', () => {
  let page: ModelRequests;
  let list: ReturnType<typeof vi.fn>;
  let vote: ReturnType<typeof vi.fn>;
  let undoVote: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    list = vi.fn().mockResolvedValue([]);
    vote = vi.fn().mockResolvedValue(makeRequest({ has_voted: true }));
    undoVote = vi.fn().mockResolvedValue(makeRequest({ request_count: 0, has_voted: false }));
    TestBed.configureTestingModule({
      providers: [
        { provide: ModelRequestService, useValue: { list, vote, undoVote } },
        {
          provide: AuthService,
          useValue: {
            currentUser: signal(makeUser([{ id: 2001, name: 'test-team' }])),
            role: signal('app_developer'),
          },
        },
      ],
    });
    page = TestBed.runInInjectionContext(() => new ModelRequests());
    await page.ngOnInit();
  });

  it('preselects the caller’s first team', async () => {
    expect(page.teamId()).toBe(2001);
  });

  it('loads the running list of requests', async () => {
    list.mockResolvedValue([makeRequest({ name: 'gpt-5', request_count: 2 })]);
    await page.refresh();
    expect(page.requests().map((r) => r.name)).toEqual(['gpt-5']);
    expect(page.loading()).toBe(false);
  });

  it('reports a load failure instead of crashing', async () => {
    list.mockRejectedValueOnce(new Error('down'));
    await page.refresh();
    expect(page.error()).toBe('Could not load model requests.');
    expect(page.requests()).toEqual([]);
  });

  it('votes for a typed model and team, trimming and clearing the field on success', async () => {
    page.name.set('  gpt-5  ');
    await page.submit();
    expect(vote).toHaveBeenCalledWith('gpt-5', 2001);
    expect(page.name()).toBe('');
    expect(page.notice()).toContain('gpt-5');
  });

  it('submits for the switched team', async () => {
    page.onTeamChange('2002');
    expect(page.teamId()).toBe(2002);
    page.name.set('gpt-5');
    await page.submit();
    expect(vote).toHaveBeenCalledWith('gpt-5', 2002);
  });

  it('ignores an empty submission', async () => {
    page.name.set('   ');
    await page.submit();
    expect(vote).not.toHaveBeenCalled();
    expect(undoVote).not.toHaveBeenCalled();
  });

  it('ignores a submission while no team is selected', async () => {
    page.onTeamChange('');
    page.name.set('gpt-5');
    await page.submit();
    expect(vote).not.toHaveBeenCalled();
  });

  it('casts a vote on an unvoted listed model', async () => {
    await page.toggle(makeRequest({ id: 2, name: 'llama', request_count: 0, has_voted: false }));
    expect(vote).toHaveBeenCalledWith('llama', 2001);
    expect(undoVote).not.toHaveBeenCalled();
  });

  it('undoes a vote on a listed model the caller already voted for', async () => {
    await page.toggle(makeRequest({ id: 2, name: 'llama', request_count: 1, has_voted: true }));
    expect(undoVote).toHaveBeenCalledWith('llama');
    expect(vote).not.toHaveBeenCalled();
  });

  it('surfaces the backend error in the failure modal and keeps the typed name', async () => {
    vote.mockRejectedValueOnce({ error: { error: 'This model is already available in Logos.' } });
    page.name.set('gpt-4');
    await page.submit();
    // Vote failures go to the modal, not the inline load-error line ...
    expect(page.voteError()).toBe('This model is already available in Logos.');
    expect(page.error()).toBeNull();
    // ... and the field is kept so the user can correct the name instead of retyping.
    expect(page.name()).toBe('gpt-4');
  });

  it('clears the failure modal when closed', async () => {
    vote.mockRejectedValueOnce({ error: { error: 'This model is already available in Logos.' } });
    page.name.set('gpt-4');
    await page.submit();
    expect(page.voteError()).not.toBeNull();
    page.closeVoteError();
    expect(page.voteError()).toBeNull();
  });

  it('does nothing for a caller without teams', async () => {
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [
        { provide: ModelRequestService, useValue: { list, vote, undoVote } },
        {
          provide: AuthService,
          useValue: {
            currentUser: signal(makeUser([])),
            role: signal('logos_admin'),
          },
        },
      ],
    });
    page = TestBed.runInInjectionContext(() => new ModelRequests());
    await page.ngOnInit();
    expect(page.teamId()).toBeNull();
    page.name.set('gpt-5');
    await page.submit();
    expect(vote).not.toHaveBeenCalled();
  });
});
