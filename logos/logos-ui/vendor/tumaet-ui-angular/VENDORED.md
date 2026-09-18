# Vendored: @tumaet/ui-angular

This directory is the compiled output (`ng-packagr` build) of the `packages/tum-ui`
library from the Artemis monorepo. It is checked in directly because
`@tumaet/ui-angular` is `private: true` inside Artemis, is not published to any
npm registry, and is only ever consumed there via pnpm's `workspace:*` protocol.
There is no other repo (inside or outside ls1intum) that installs it externally,
so there's no existing "git dependency" pattern to reuse.

- Source: https://github.com/ls1intum/Artemis, `packages/tum-ui`
- Built from commit: `aa16f3b0877153efd41496b6ef64272f3773e3c8`
- Built against the exact toolchain versions pinned in that commit's
  `pnpm-workspace.yaml` catalog: `@angular/core@22.1.6`, `ng-packagr@22.1.1`,
  `typescript@6.0.3`, `@tailwindcss/postcss@4.3.3`, etc.

## Consuming it

`logos-ui/package.json` depends on it via `"@tumaet/ui-angular": "file:./vendor/tumaet-ui-angular"`.
That's a plain local package reference — `npm ci`/`npm install` needs no extra
scripts or registries to resolve it.

Peer dependencies (must stay satisfied in `logos-ui/package.json`):
`@angular/cdk`, `@angular/common`, `@angular/core`, `@angular/forms` @ `22.1.6`,
`@fortawesome/angular-fontawesome@5.1.0`, `@fortawesome/fontawesome-svg-core@7.3.1`,
`@fortawesome/free-solid-svg-icons@7.3.1`, `rxjs@7.8.2`.

## Rebuilding / updating

There's no automation for this — it's a manual, occasional refresh:

1. Sparse-clone `ls1intum/Artemis` at the desired commit, checking out `packages/tum-ui`.
2. Read that commit's root `pnpm-workspace.yaml` for the exact catalog versions
   `packages/tum-ui/package.json` references.
3. In a scratch pnpm workspace, replace the `catalog:` devDependency entries
   with those concrete versions (trim to only what the `build` script needs:
   the `@angular/*` compiler/CDK packages, `ng-packagr`, `@tailwindcss/postcss`,
   `postcss`, `tailwindcss`, `sass`, `chokidar`, `typescript`, `zone.js`, the
   `@fortawesome/*` peers, and `@types/lodash-es` — the last one is missing
   from Artemis's own devDependency list but is required for a clean
   `ng-packagr` compile standalone).
4. `pnpm install && pnpm run build` inside `packages/tum-ui`.
5. Copy `packages/tum-ui/dist/*` over this directory's contents, and update
   this file's "Built from commit" line.
6. Bump `logos-ui/package.json`'s Angular/fortawesome/rxjs versions to match
   whatever the new build's peerDependencies require.
