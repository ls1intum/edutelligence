import React from "react";
import Link from "@docusaurus/Link";
import useBaseUrl from "@docusaurus/useBaseUrl";
import styles from "./styles.module.css";

export default function HeroSection(): React.JSX.Element {
  return (
    <header className={styles.hero}>
      <img
        src={useBaseUrl("/img/iris/iris-logo-big-right.png")}
        alt="Iris mascot"
        className={styles.heroLogo}
      />
      <h1 className={styles.heroHeadline}>
        The AI tutor that teaches, not just <em>answers</em>
      </h1>
      <p className={styles.heroSubtitle}>
        Iris is a context-aware virtual tutor integrated into Artemis. It
        provides scaffolded hints, guided learning, and grounded responses
        &mdash; designed to preserve productive struggle and foster genuine
        understanding.
      </p>
      <div className={styles.heroCtas}>
        <Link className={styles.btnPrimary} to="/docs/overview/what-is-iris">
          Get Started
        </Link>
        <a
          className={styles.btnGhost}
          href="https://github.com/ls1intum/edutelligence"
          target="_blank"
          rel="noopener noreferrer"
        >
          View on GitHub
        </a>
      </div>
    </header>
  );
}
