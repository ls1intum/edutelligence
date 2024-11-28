/** @type {import("prettier").Config} */
const config = {
  arrowParens: "always",
  bracketSameLine: true,
  bracketSpacing: true,
  endOfLine: "lf",
  htmlWhitespaceSensitivity: "ignore",
  jsxSingleQuote: false,
  printWidth: 100,
  proseWrap: "never",
  quoteProps: "as-needed",
  semi: true,
  singleQuote: false,
  tabWidth: 2,
  useTabs: false,
  trailingComma: "all",
  plugins: ["prettier-plugin-tailwindcss"],
  tailwindFunctions: ["cn"],
};

module.exports = config;
