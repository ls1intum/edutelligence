/** @type {import('eslint').Linter.Config} */
module.exports = {
    root: true,
    parserOptions: {
        ecmaVersion: "latest",
        sourceType: "module",
        ecmaFeatures: {
            jsx: true,
        },
    },
    env: {
        browser: true,
        commonjs: true,
        es6: true,
    },

    // Base config
    extends: ["eslint:recommended", "prettier", "plugin:@next/next/recommended"],

    rules: {
        "no-console": "warn",
        "react/jsx-curly-brace-presence": [2, { props: "never", children: "never" }],
        "react/no-unknown-property": [
            2,
            {
                ignore: ["jsx"],
            },
        ],
        "@typescript-eslint/explicit-function-return-type": "off",
        "no-restricted-syntax": [
            "error",
            // Ensure import from 'react' is not `useLayoutEffect`
            {
                selector:
                    'ImportDeclaration[source.value="react"] > ImportSpecifier[imported.name="useLayoutEffect"]',
                message: "Please use ``useLayoutEffect` from custom hook `useIsomorphicLayoutEffect",
            },
            // Ensure import from '*useIsomorphicLayoutEffect' is `useLayoutEffect` to leverage `eslint-plugin-react-hooks`
            {
                selector:
                    'ImportDeclaration[source.value=/useIsomorphicLayoutEffect/] > ImportDefaultSpecifier[local.name!="useLayoutEffect"]',
                message:
                    "Must use `useLayoutEffect` as the name of the import from `*useIsomorphicLayoutEffect` to leverage `eslint-plugin-react-hooks`",
            },
        ],
    },

    overrides: [
        // React
        {
            files: ["**/*.{js,jsx,ts,tsx}"],
            plugins: ["react", "jsx-a11y"],
            extends: [
                "plugin:react/recommended",
                "plugin:react/jsx-runtime",
                "plugin:react-hooks/recommended",
                "plugin:jsx-a11y/recommended",
            ],
            settings: {
                react: {
                    version: "detect",
                },
                formComponents: ["Form", "ValidatedForm"],
                linkComponents: [
                    { name: "Link", linkAttribute: "to" },
                    { name: "NavLink", linkAttribute: "to" },
                ],
                "import/resolver": {
                    typescript: {},
                },
            },
        },
        // shadcn
        {
            files: ["**/components/ui/*.tsx"],
            rules: {
                "react/prop-types": "off",
                "react-refresh/only-export-components": "off",
            },
        },

        // Typescript
        {
            files: ["**/*.{ts,tsx}"],
            plugins: ["@typescript-eslint", "import"],
            parser: "@typescript-eslint/parser",
            settings: {
                "import/internal-regex": "^~/",
                "import/resolver": {
                    node: {
                        extensions: [".ts", ".tsx"],
                    },
                    typescript: {
                        alwaysTryTypes: true,
                    },
                },
            },
            extends: [
                "plugin:@typescript-eslint/recommended",
                "plugin:import/recommended",
                "plugin:import/typescript",
            ],
        },

        // Node
        {
            files: [".eslintrc.js"],
            env: {
                node: true,
            },
        },
    ],
};