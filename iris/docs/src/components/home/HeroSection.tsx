import React from "react";
import Link from "@docusaurus/Link";
import useBaseUrl from "@docusaurus/useBaseUrl";
import styles from "./styles.module.css";

export default function HeroSection(): React.JSX.Element {
  return (
    <div className={styles.heroWrapper}>
      <div className={styles.heroSplit}>
        <header className={styles.hero}>
          <img
            src={useBaseUrl("/img/iris/iris-logo-big-right.png")}
            alt="Iris mascot"
            className={styles.heroLogo}
          />
          <h1 className={styles.heroHeadline}>
            AI That <em>Teaches</em>, Not Just Answers
          </h1>
          <p className={styles.heroSubtitle}>
            Grounded in your course materials. Built into Artemis. Backed by 3
            peer-reviewed studies at TU Munich.
          </p>
          <p className={styles.heroProof}>
            <span aria-hidden="true">🎓</span> 30,000+ conversations powered at
            TU Munich
          </p>
          <div className={styles.heroCtas}>
            <a className={styles.btnPrimary} href="mailto:krusche@tum.de">
              Request a Demo
            </a>
            <Link className={styles.btnGhost} to="/docs/research/publications">
              Read the Research
            </Link>
          </div>
        </header>
        <div className={styles.heroVisual}>
          <img
            src={useBaseUrl("/img/screenshots/iris-chat-response-hd.png")}
            alt="Iris AI tutor responding to a student question in Artemis with a citation to lecture slides"
            className={styles.heroScreenshot}
            width={960}
            height={540}
          />
        </div>
      </div>
    </div>
  );
}
