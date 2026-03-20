import { themes as prismThemes } from "prism-react-renderer";
import type { Config } from "@docusaurus/types";
import type * as Preset from "@docusaurus/preset-classic";

const config: Config = {
  title: "Iris",
  tagline: "The AI tutor that teaches, not just answers",
  favicon: "img/iris/iris-logo-small.png",

  future: {
    v4: true,
  },

  url: "https://ls1intum.github.io",
  baseUrl: "/edutelligence/iris/",

  organizationName: "ls1intum",
  projectName: "edutelligence",

  onBrokenLinks: "throw",

  markdown: {
    hooks: {
      onBrokenMarkdownLinks: "warn",
    },
  },

  i18n: {
    defaultLocale: "en",
    locales: ["en"],
  },

  presets: [
    [
      "classic",
      {
        docs: {
          sidebarPath: "./sidebars.ts",
          editUrl:
            "https://github.com/ls1intum/edutelligence/tree/main/iris/docs/",
        },
        blog: false,
        theme: {
          customCss: "./src/css/custom.css",
        },
      } satisfies Preset.Options,
    ],
  ],

  plugins: [
    [
      "@easyops-cn/docusaurus-search-local",
      {
        hashed: true,
        language: ["en"],
        docsRouteBasePath: ["docs"],
        docsDir: [
          "docs/overview",
          "docs/student",
          "docs/instructor",
          "docs/developer",
          "docs/admin",
          "docs/research",
        ],
        indexBlog: false,
        searchContextByPaths: [
          { label: { en: "Overview" }, path: "docs/overview" },
          { label: { en: "Student Guide" }, path: "docs/student" },
          { label: { en: "Instructor Guide" }, path: "docs/instructor" },
          { label: { en: "Developer Guide" }, path: "docs/developer" },
          { label: { en: "Admin Guide" }, path: "docs/admin" },
          { label: { en: "Research" }, path: "docs/research" },
        ],
        hideSearchBarWithNoSearchContext: true,
        useAllContextsWithNoSearchContext: false,
        highlightSearchTermsOnTargetPage: true,
        searchResultContextMaxLength: 60,
      },
    ],
  ],

  themeConfig: {
    image: "img/iris/iris-logo-big-right.png",
    colorMode: {
      respectPrefersColorScheme: true,
    },
    navbar: {
      title: "Iris",
      logo: {
        alt: "Iris Logo",
        src: "img/iris/iris-logo-small.png",
      },
      items: [
        {
          type: "docSidebar",
          sidebarId: "overviewSidebar",
          position: "left",
          label: "Overview",
        },
        {
          type: "docSidebar",
          sidebarId: "studentSidebar",
          position: "left",
          label: "Student Guide",
        },
        {
          type: "docSidebar",
          sidebarId: "instructorSidebar",
          position: "left",
          label: "Instructor Guide",
        },
        {
          type: "docSidebar",
          sidebarId: "developerSidebar",
          position: "left",
          label: "Developer Guide",
        },
        {
          type: "docSidebar",
          sidebarId: "adminSidebar",
          position: "left",
          label: "Admin Guide",
        },
        {
          type: "docSidebar",
          sidebarId: "researchSidebar",
          position: "left",
          label: "Research",
        },
        { type: "search", position: "right" },
        {
          href: "https://github.com/ls1intum/edutelligence",
          label: "GitHub",
          position: "right",
        },
      ],
    },
    footer: {
      style: "dark",
      links: [
        {
          title: "Guides",
          items: [
            { label: "Student Guide", to: "/docs/student/getting-started" },
            { label: "Instructor Guide", to: "/docs/instructor/enabling-iris" },
            { label: "Developer Guide", to: "/docs/developer/local-setup" },
          ],
        },
        {
          title: "Community",
          items: [
            {
              label: "GitHub",
              href: "https://github.com/ls1intum/edutelligence",
            },
            { label: "Artemis", href: "https://github.com/ls1intum/Artemis" },
          ],
        },
        {
          title: "Research",
          items: [
            { label: "Publications", to: "/docs/research/publications" },
            { label: "Citing Iris", to: "/docs/research/citing-iris" },
          ],
        },
      ],
      copyright: `Copyright © ${new Date().getFullYear()} Technical University of Munich. Built with Docusaurus.`,
    },
    prism: {
      theme: prismThemes.github,
      darkTheme: prismThemes.dracula,
    },
  } satisfies Preset.ThemeConfig,
};

export default config;
