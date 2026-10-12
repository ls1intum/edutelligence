# Logos UI

This project was generated using [Angular CLI](https://github.com/angular/angular-cli) version 21.2.10.

## Development server

To start a local development server, run:

```bash
ng serve
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
ng build
```

This will compile your project and store the build artifacts in the `dist/` directory. By default, the production build optimizes your application for performance and speed.

## Running unit tests

To execute unit tests with the [Vitest](https://vitest.dev/) test runner, use the following command:

```bash
ng test
```

## Running end-to-end tests

For end-to-end (e2e) testing, run:

```bash
ng e2e
```

Angular CLI does not come with an end-to-end testing framework by default. You can choose one that suits your needs.

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

The model **Performance** tab supports configurable single runs and batches.
**Review & start benchmark** opens the shared `app-modal-confirm` component used
for team deletion. Closing the dialog cancels the draft start; confirming submits
the job once. The dialog explains lane reservation and persistent vLLM changes.

The comparison component renders one eligible measurement as a filled point with
`n = 1`. Multiple measurements use a boxplot. Recorded configuration controls and
successful completion remain required for comparison.

See [Configurable model benchmarks](../logos-orchestrator/docs/benchmark-configuration.md)
for reservation behavior, failed-model preparation, batch cancellation and Dev checks.
See [GuideLLM → Logos](../benchmarks/GUIDELLM.md) for the separate command-line runner.

### Benchmark confirmation preview

The shared confirmation dialog explains the temporary reservation before a job
starts. This screenshot uses synthetic data in the actual component, without
live services or the authenticated application shell.

![Shared benchmark confirmation dialog on desktop](https://gist.githubusercontent.com/Tim0x54/72219bc2b43197e7ddbeeae1029c6fd4/raw/86590c8c73b36a555202752af495cdd7f7dbba13/logos-pr-desktop-dialog.png)

See the [desktop and mobile screenshot walkthrough](../logos-orchestrator/docs/benchmark-configuration.md#screenshots)
for the settings, comparison charts and 375px layouts.

## Additional Resources

For more information on using the Angular CLI, including detailed command references, visit the [Angular CLI Overview and Command Reference](https://angular.dev/tools/cli) page.
