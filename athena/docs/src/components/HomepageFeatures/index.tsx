import type {ReactNode} from 'react';
import Heading from '@theme/Heading';
import Link from '@docusaurus/Link';

import styles from './styles.module.css';

const guideLinks = [
  {
    title: 'User Guide',
    description: 'Operate the Athena Playground, run experiments, and grade with AI-assisted modules.',
    to: '/docs/user/overview/athena',
  },
  {
    title: 'Developer Guide',
    description: 'Set up the mono-repo, develop assessment modules, and ship reliable evaluations.',
    to: '/docs/dev/setup/install',
  },
  {
    title: 'Admin Guide',
    description: 'Deploy Athena, wire LMS bridges, and keep services monitored end to end.',
    to: '/docs/admin/administration_of_deployments/configuration',
  },
];

export default function HomepageFeatures(): ReactNode {
  return (
    <section className={styles.quickstartSection}>
      <div className="container">
        <div className={styles.quickstartHeader}>
          <Heading as="h2">Pick the guide that matches your role</Heading>
          <p>
            Whether you are piloting AI-assisted grading, extending assessment modules, or maintaining deployments,
            the docs below mirror the workflows in Athena.
          </p>
        </div>
        <div className={styles.quickstartGrid}>
          {guideLinks.map((guide) => (
            <Link key={guide.title} className={styles.quickstartCard} to={guide.to}>
              <div>
                <Heading as="h3">{guide.title}</Heading>
                <p>{guide.description}</p>
              </div>
              <span aria-hidden="true">→</span>
            </Link>
          ))}
        </div>
      </div>
    </section>
  );
}
