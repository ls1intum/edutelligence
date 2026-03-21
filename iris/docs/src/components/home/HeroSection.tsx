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
      <p className={styles.heroProof}>
        Used by 1,600+ students at the Technical University of Munich
      </p>
      <div className={styles.heroCtas}>
        <Link className={styles.btnPrimary} to="/docs/overview/what-is-iris">
          See How It Works
        </Link>
        <Link className={styles.btnGhost} to="/docs/research/publications">
          Read the Research
        </Link>
      </div>
    </header>
  );
}
