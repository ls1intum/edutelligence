# AGENTS.md — logos-ui

Angular 22 web application for Logos (teams, API keys, models, stats, batches), served behind Traefik on the same origin as the APIs in production.

## Commands

```bash
npm ci                 # install
npm start              # dev server on :4200 (ng serve) — pair with the dev compose stack
npm run build          # production build
npm test               # unit tests (ng test)
npm run e2e:install    # one-time: playwright chromium
npm run e2e            # Playwright suite — needs the full stack up via ../e2e (see ../e2e/README.md)
```

## Conventions

- **Screenshots are MANDATORY for every UI PR** (desktop + mobile, full page, hosted in a gist, embedded in the PR description, never committed). Follow the `ui-screenshots` skill (`../.agents/skills/ui-screenshots/SKILL.md`) exactly.
- UI components come from the **vendored** `@tumaet/ui-angular` (TUM UI design system): the compiled `ng-packagr` output of `packages/tum-ui` in `ls1intum/Artemis`, checked in under `vendor/tumaet-ui-angular/` and consumed via a `file:` dependency because the package is not published to a registry yet. Never edit it by hand, and keep its peer dependency versions (`@angular/*`, `@fortawesome/*`, `rxjs`) matched in `package.json`. The manual refresh procedure is in `vendor/tumaet-ui-angular/VENDORED.md`. Once the package is published, this is replaced by an ordinary npm dependency.
- The shared data tables drop their header below 768px and fall back to per-cell `data-label`s — verify tables at a 375px viewport.
- The app scrolls inside an inner container, not the document — the `ui-screenshots` skill has the unlock procedure for a true full-page screenshot.
- Login during local dev goes through Keycloak; seeded users (all password `password`) are listed in `../README.md` (`tobias.wasner` = logos admin).
