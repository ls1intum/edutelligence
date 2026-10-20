# Logos UI

Angular web application for Logos. Dependency versions are in `package.json`.

## Development server

Start the services described in the [Logos README](../README.md), then run:

```bash
npm ci
npm start
```

Once the server is running, open your browser and navigate to `http://localhost:4200/`. The application will automatically reload whenever you modify any of the source files.

## Code scaffolding

Angular CLI includes powerful code scaffolding tools. To generate a new component, run:

```bash
ng generate component component-name
```

For a complete list of available schematics (such as `components`, `directives`, or `pipes`), run:

```bash
ng generate --help
```

## Building

To build the project run:

```bash
npm run build
```

This will compile your project and store the build artifacts in the `dist/` directory. By default, the production build optimizes your application for performance and speed.

## Running unit tests

To execute unit tests with the [Vitest](https://vitest.dev/) test runner, use the following command:

```bash
npm test
```

## Running end-to-end tests

For end-to-end (e2e) testing, run:

```bash
npm run e2e:install
npm run e2e
```

The Playwright suite requires the running stack. See the [E2E guide](../e2e/README.md).

## Design System

Colors, fonts, and spacing are CSS variables in `src/styles/_tokens.scss`
(light/dark themed). Shared buttons/typography classes live in
`src/styles/_buttons.scss` and `_typography.scss` (`.btn-primary`,
`.page-title`, etc). No webfonts are downloaded: typography uses the system
font stacks in `--font-family-base` / `--font-family-display` /
`--font-family-mono` (`src/styles/_tokens.scss`).

Reusable components live in `src/app/shared/components/`: `app-select`,
`app-search-input`, `app-data-table`, `app-modal-form`, `app-modal-confirm`,
`app-icon-tile`, `app-role-badge`, `app-error-message`, `app-time-range-bar`,
`app-theme-toggle`. Check there before building a new one.

## Model-provider benchmarks

The model **Performance** tab separates **Results** from **Run benchmark**.
**Review benchmark** or **Review batch** opens the shared `app-modal-confirm`
component used for team deletion. Only confirmation submits the job.
Switching views preserves the draft settings.

The comparison component renders one eligible measurement as a filled point with
`n = 1`. Multiple measurements use a boxplot. Recorded configuration controls and
successful completion remain required for comparison.

See the [Model Benchmarks guide](../docs/admin/model-benchmarks.md) for the user
workflow and desktop screenshots.
See [Configurable model benchmarks](../logos-orchestrator/docs/benchmark-configuration.md)
for reservation behavior, failed-model preparation, batch cancellation and Dev checks.
See [GuideLLM → Logos](../benchmarks/GUIDELLM.md) for the separate command-line runner.

## Additional Resources

For more information on using the Angular CLI, including detailed command references, visit the [Angular CLI Overview and Command Reference](https://angular.dev/tools/cli) page.
