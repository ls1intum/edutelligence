# Logos UI

This project was generated using [Angular CLI](https://github.com/angular/angular-cli) version 21.2.10.

## Nightly benchmarks in Model Details

The [illustrated admin walkthrough](../docs/roles/logos-admin.md#nightly-benchmarks)
shows the plan and both confirmation dialogs.

A Logos Admin opens **Models → Model Details → Performance**. Each Logos worker
pair has a **Nightly benchmarks** card above the manual benchmark editor.

The card shows the model, **Parameters to be tested**, activation state and the
latest schedule state. It lists concrete values from the status API. Unknown
serving limits show **Current configuration only**. This preview reflects the
current worker settings; the scheduler constructs the plan again at run start.

Choose **Enable nightly runs…** and confirm **Enable nightly runs** to add the
pair to the rotation. Choose **Disable nightly runs…** and confirm
**Disable nightly runs** to remove it. **Cancel** leaves the saved state unchanged.
The schedule remains active after closing the page. Disabling also cancels an
active nightly run and restores the worker before production traffic resumes.

The rotation selects up to two enabled pairs per night, with never-tested pairs
first and the oldest previous attempt next. Selection is not a guarantee that
every enabled pair runs tonight: worker availability and time limits still apply.

The dataset selector and question previews below the card belong to the manual
benchmark editor. Changing that editor does not change the fixed nightly
workload. **Latest nightly results** shows configuration outcomes and retries;
successful measurements also appear in the existing performance comparison.

See the [nightly benchmark guide](../logos-orchestrator/docs/nightly-benchmarks.md)
for the fixed workload, time limits, recovery and deployment requirements.

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

## Additional Resources

For more information on using the Angular CLI, including detailed command references, visit the [Angular CLI Overview and Command Reference](https://angular.dev/tools/cli) page.
