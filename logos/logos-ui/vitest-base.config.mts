import { defineConfig, type Plugin } from 'vitest/config';

/**
 * The published @tumaet/ui-angular bundle imports the `dayjs/esm` directory,
 * which Node's ESM loader rejects while the package stays externalized.
 * Marking it `noExternal` routes the bundle through the Vite resolver, which
 * handles the directory import. The unit-test builder constructs its test
 * project without inheriting this root configuration, so the override is
 * returned from a plugin hook — the builder merges user plugins from this
 * file into the project, where the hook runs.
 */
function inlineUiAngular(): Plugin {
  return {
    name: 'logos-ui:inline-ui-angular',
    config() {
      return {
        resolve: {
          noExternal: ['@tumaet/ui-angular'],
        },
      };
    },
  };
}

export default defineConfig({
  plugins: [inlineUiAngular()],
});
