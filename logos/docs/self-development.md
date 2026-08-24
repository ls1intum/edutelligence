# Self-development: Logos developing Logos

Logos already serves the class of models that coding agents run on, and Logos is
already developed with those agents. This document records how that loop is
wired today, what it is missing, and which properties of our architecture decide
how far it can go.

It is a design document, not a proposal to automate everyone's job away. The
boundary conditions matter more than the ambition, so they come first.

## Where we are

Three modes of agent participation exist in this repository today. They differ
in who holds the identity and who holds the context, and that difference decides
what each mode needs from us.

| Mode | Agent runs | Identity on the commit | Human involvement |
|---|---|---|---|
| **Agent-assisted** | In a maintainer's working copy | The maintainer, with a `Co-Authored-By: Claude` trailer | Continuous — the maintainer steers and reviews as the work happens |
| **Agent-authored** | On a VM or on the forge | The agent's own account (`Claudia-Anthropica`, `copilot-swe-agent`) | At the boundaries — an issue in, a review and merge out |
| **Human** | — | The maintainer | Everything |

Measured over the repository history (see the case study linked at the bottom):
agent-assisted work began 2026-02-23 and now accounts for roughly half of all
Logos commits; agent-authored work began 2026-08-12 and stands at four merged
pull requests. The sibling services in this monorepository — same review
process, same CI — are at essentially zero.

### What the platform already provides

- **An Anthropic Messages surface.** `/v1/messages` on the orchestrator speaks
  the format Claude Code expects, so an agent can be pointed at Logos instead of
  at the vendor.
- **A configuration generator.** The AI tools page
  (`logos-ui/src/app/features/ai-tools/`) emits a working `settings.json` for
  Claude Code and an `opencode.json` for OpenCode, against a chosen key and
  model, with the context and output budgets computed from the model's real
  window.
- **Compatibility fixes for agent traffic.** `pipeline/effort_normalization.py`
  rewrites a session's reasoning effort onto the scale a local model's chat
  template accepts, because Claude Code attaches an effort to every request and
  some templates reject the out-of-scale values with a 500.

That last item is the pattern worth noticing: it is a defect that exists only
because an agent is a client, and it was found and fixed while working with an
agent. We have been improving the conditions of our own development for months
without calling it that.

### What is not wired yet

**The loop is available, not closed.** Agents developing Logos today call the
commercial endpoint, not Logos. Everything needed to change that exists; nobody
has flipped it for the agent-authored runners.

**Steering happens in terminals.** Agent-authored runs are addressed through
GitHub issues. There is no view in Logos of what an agent was asked, what it may
touch, what it is doing, what it has cost, or where its work is waiting.

## The boundary that decides everything

An agent can change what the repository represents, and nothing else. This is
not a limitation of a particular tool; it is what the participant *is*. It has
one consequence we keep re-learning:

> Worker-node `config.yml` is in this repository, and it is not the file that
> runs. The effective copy is maintained by Ansible on each host. So is
> `chat-templates/`. An agent — or a new contributor — can edit the versioned
> copy, watch CI go green, and ship a change that takes no effect.

A shadow file is worse than a missing one, because it supplies confidence where
absence would supply none. And the same edge that stops the agent stops our
measurement: a fault that lives in an unversioned config file leaves no trace in
the repository, so no amount of history mining will find it.

Three properties are lost together at that edge, because they have one cause:

1. the work is **not delegable** — no agent can act on it;
2. the change is **not automatically verifiable** — CI cannot exercise it;
3. the outcome is **not measurable** — the repository has no record of it.

This gives a concrete question to ask of any decision that governs runtime
behaviour: *is the authoritative expression of this decision inside the
repository, or outside it?*

### What that implies for us

- **Move node configuration into the artefact space, or make its absence
  explicit.** Either version the effective `config.yml` per host and have the
  deploy render it, or make the checked-in copy fail loudly when it is treated
  as authoritative. Today it does neither. This is the single highest-value
  change on this list, and it pays off for human contributors regardless of any
  agent.
- **Give the operational layer a verifiable surface.** Lane profiles, model
  calibration, and capability declarations are runtime state today. Wherever a
  declared value can be checked against a measured one, that check belongs in
  CI or in a startup assertion, not in an operator's memory.
- **Keep the CI gate honest.** Build and CI configuration is the most
  repair-intensive class in the service — it absorbs about 2.5× its share of
  fault-inducing edits. It is also where agents work most. That combination
  argues for treating the CI configuration as production code, not scaffolding.

## Closing the loop, deliberately

If agents that develop Logos are served by Logos, an outage removes the
capability that would repair it, exactly when it is needed. The failure is
correlated with its own remedy.

That is not an argument against closing the loop. It is an argument for
designing the recovery path first:

- keep a **credentialled escape hatch** to an independently operated provider,
  configured and exercised often enough to be known to work;
- treat it as a **recovery path, not a fallback** — it must be usable when the
  platform is at its worst, which means it cannot depend on the platform's
  scheduler, its database, or its key store;
- **exercise it on a schedule**, since an untested recovery path is a story
  about a recovery path.

The same reasoning keeps a build system from depending on the artefact it
builds. It is only unfamiliar here because the dependency is new.

## The steering interface

Moving from agent-assisted to agent-authored moves the cost. In the assisted
mode the maintainer sees the work as it happens. In the authored mode the pull
request is the *first* point a human sees it, and the issue text is the whole
specification. Our four agent-authored pull requests merged an order of
magnitude more slowly than assisted ones and half drew a changes-requested
verdict — a sample too small to conclude from, but pointing at where the effort
goes.

More autonomy therefore does not need a better agent so much as a better place
for a human to stand. A steering view in Logos would need to expose, per run:

- **the assignment** — the issue or prompt the agent was given;
- **the permitted scope** — which paths, which commands, which credentials;
- **live progress** — what it is doing now, and what it has changed so far;
- **cost and model** — tokens, provider, and which model served the run, which
  Logos already records for every request;
- **the intervention point** — a way to stop, redirect, or take over *before*
  the pull request exists, not only at review time.

The first four are largely a matter of surfacing data Logos already has: an
agent run is a sequence of requests under one key, and we already log those. The
fifth is the genuinely new piece, and it is the one that decides whether
supervision is real or ceremonial.

## Guardrails we should not skip

- **Agents get their own identity and their own key.** Never a maintainer's.
  This is what makes participation auditable and revocable — and it is why
  `Claudia-Anthropica` is the right shape already.
- **Agent keys carry the narrowest permission set that works.** They are, in
  Logos terms, ordinary keys with policies and limits; use them.
- **Merge stays human.** An approving review by a person is the control point.
  Nothing in this document proposes changing that.
- **Every run is attributable after the fact.** The commit trailer, the pull
  request author, and the request log should agree on who did what. They
  currently do, and that is precisely why the case study below was possible.

## Further reading

- [Request lifecycle](../logos-orchestrator/src/logos/pipeline/README.md) —
  classification, scheduling, and context resolution
- [Node provider setup](../logos-orchestrator/docs/node-provider-setup.md) —
  what Ansible owns on a worker host and what this repository owns
- The empirical case study this document draws on measures the repository
  history behind these claims: 1446 commits, 613 pull requests, and 10066
  fix-to-cause links across all services. Ask @wasnertobias for the draft.
