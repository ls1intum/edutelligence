import type {ReactNode} from 'react';
import Link from '@docusaurus/Link';
import useDocusaurusContext from '@docusaurus/useDocusaurusContext';
import Layout from '@theme/Layout';
import HomepageFeatures from '@site/src/components/HomepageFeatures';
import Heading from '@theme/Heading';

import styles from './index.module.css';

function HomepageHeader() {
  return (
    <header className={styles.heroSection}>
      <div className="container">
        <div className={styles.heroCopy}>
          <Heading as="h1" className={styles.heroTitle}>
            AI-assisted assessment for scalable, fair tutoring — integrated with your LMS.
          </Heading>
          <p className={styles.heroSubtitle}>
            Athena coordinates LMS integrations, AI-assisted modules, and evaluation workflows so
            feedback stays fast, fair, and auditable across every course.
          </p>
          <div className={styles.heroActions}>
            <Link className="button button--primary button--lg" to="/docs/user/overview/athena">
              Browse the User Guide
            </Link>
            <Link
              className="button button--link button--lg"
              href="https://github.com/ls1intum/edutelligence/tree/main/athena">
              View the repository
            </Link>
          </div>
        </div>
      </div>
    </header>
  );
}

export default function Home(): ReactNode {
  const {siteConfig} = useDocusaurusContext();
  return (
    <Layout
      title={siteConfig.title}
      description="Athena documentation for LMS integrations, assessment modules, experiments, and production deployments.">
      <HomepageHeader />
      <main>
        <HomepageFeatures />
      </main>
    </Layout>
  );
}
