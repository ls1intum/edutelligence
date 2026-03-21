import React from "react";
import Link from "@docusaurus/Link";
import useBaseUrl from "@docusaurus/useBaseUrl";
import styles from "./styles.module.css";

export default function HeroSection(): React.JSX.Element {
  return (
    <div className={styles.heroWrapper}>
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
          An AI tutor built into Artemis that helps students learn by guiding
          them to the answer &mdash; not giving it away.
        </p>
        <p className={styles.heroProof}>Used by 1,600+ students at TU Munich</p>
        <div className={styles.heroCtas}>
          <a className={styles.btnPrimary} href="#comparison">
            See How It Works
          </a>
          <Link className={styles.btnGhost} to="/docs/research/publications">
            Read the Research
          </Link>
        </div>
      </header>
    </div>
  );
}
