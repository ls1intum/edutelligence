import { themes as prismThemes } from "prism-react-renderer";
import type { Config } from "@docusaurus/types";
import type * as Preset from "@docusaurus/preset-classic";

const config: Config = {
  title: "Logos",
  tagline: "LLM engineering made easy",
  url: "https://ls1intum.github.io",
  baseUrl: "/edutelligence/logos/",
  organizationName: "ls1intum",
  projectName: "edutelligence",
  onBrokenLinks: "throw",
  future: { v4: true },
  i18n: { defaultLocale: "en", locales: ["en"] },
  presets: [
    [
      "classic",
      {
        docs: {
          path: ".",
          exclude: ["**/node_modules/**", "**/build/**"],
          routeBasePath: "/",
          sidebarPath: "./sidebars.ts",
          editUrl: "https://github.com/ls1intum/edutelligence/tree/main/logos/docs/",
        },
        blog: false,
        theme: { customCss: "./src/css/custom.css" },
      } satisfies Preset.Options,
    ],
  ],
  themeConfig: {
    colorMode: { respectPrefersColorScheme: true },
    navbar: {
      logo: {
        alt: "Logos",
        src: "img/logos-logo.svg",
      },
      title: "Logos Documentation",
      items: [
        { type: "docSidebar", sidebarId: "userSidebar", label: "User Guide", position: "left" },
        { type: "docSidebar", sidebarId: "adminSidebar", label: "Administrator Guide", position: "left" },
        { type: "docSidebar", sidebarId: "developerSidebar", label: "Developer Guide", position: "left" },
        { type: "docSidebar", sidebarId: "rolesSidebar", label: "Roles", position: "left" },
        { href: "https://github.com/ls1intum/edutelligence", label: "GitHub", position: "right" },
      ],
    },
    footer: {
      style: "dark",
      links: [
        { title: "Guides", items: [
          { label: "User Guide", to: "/user/getting-started" },
          { label: "Administrator Guide", to: "/admin/installation" },
          { label: "Developer Guide", to: "/developer/local-setup" },
          { label: "Roles and Pages", to: "/roles/app-developer" },
        ] },
        { title: "Community", items: [
          { label: "GitHub", href: "https://github.com/ls1intum/edutelligence" },
        ] },
      ],
      copyright: `Copyright © ${new Date().getFullYear()} Technical University of Munich. Built with Docusaurus.`,
    },
    prism: { theme: prismThemes.github, darkTheme: prismThemes.dracula },
  } satisfies Preset.ThemeConfig,
};

export default config;
