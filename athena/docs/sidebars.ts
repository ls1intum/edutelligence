import type {SidebarsConfig} from '@docusaurus/plugin-content-docs';

// This runs in Node.js - Don't use client-side code here (browser APIs, JSX...)

/**
 * Creating a sidebar enables you to:
 - create an ordered group of docs
 - render a sidebar for each doc of that group
 - provide next/previous navigation

 The sidebars can be generated from the filesystem, or explicitly defined here.

 Create as many sidebars as you want.
 */
const sidebars: SidebarsConfig = {
  userSidebar: [
    {
      type: 'category',
      label: 'Overview',
      items: ['user/overview/athena', 'user/overview/playground'],
    },
    {
      type: 'category',
      label: 'Playground Manual',
      items: [
        'user/user_guide/index',
        'user/user_guide/setup/setup',
        'user/user_guide/evaluation_data_format',
        'user/user_guide/conduct_experiment',
      ],
    },
  ],
  devSidebar: [
    {
      type: 'category',
      label: 'Setup',
      items: [
        'dev/setup/install',
        'dev/setup/pycharm',
        'dev/setup/vscode',
        'dev/setup/playground',
        'dev/setup/evaluation',
      ],
    },
    {
      type: 'category',
      label: 'Run',
      items: [
        'dev/run/pycharm',
        'dev/run/local',
        'dev/run/docker',
        'dev/run/playground',
      ],
    },
    {
      type: 'category',
      label: 'Modules',
      items: ['dev/module/structure', 'dev/module/create'],
    },
    {
      type: 'category',
      label: 'Athena Package',
      items: ['dev/athena_package/storage', 'dev/athena_package/helpers'],
    },
    {
      type: 'category',
      label: 'Testing',
      items: [
        'dev/tests/index',
        'dev/tests/test_structure',
        'dev/tests/test_execution',
        'dev/tests/mock_vs_real',
        'dev/tests/shared_utilities',
        'dev/tests/similarity_analysis',
      ],
    },
  ],
  adminSidebar: [
    'admin/administration_of_deployments/configuration',
  ],
};

export default sidebars;
