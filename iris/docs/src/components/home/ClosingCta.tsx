import React from "react";
import Link from "@docusaurus/Link";
import useBaseUrl from "@docusaurus/useBaseUrl";
import styles from "./styles.module.css";
import { useFadeIn } from "./useFadeIn";

export default function ClosingCta(): React.JSX.Element {
  const [ref, visible] = useFadeIn();

  return (
    <section className={styles.closingCtaWrapperNavy}>
      <div
        ref={ref as React.RefObject<HTMLDivElement>}
        className={`${styles.closingCta} ${styles.fadeIn} ${visible ? styles.fadeInVisible : ""}`}
      >
        <img
          src={useBaseUrl("/img/iris/iris-logo-big-right.png")}
          alt=""
          className={styles.closingCtaMascot}
          aria-hidden="true"
        />
        <h2 className={styles.closingCtaHeadline}>
          Bring Course-Grounded AI to Your Teaching
        </h2>
        <p className={styles.closingCtaSubtitle}>
          Built into Artemis. Studied at TU Munich. Used by 1,600+ students.
          Talk to the team about a pilot, or explore the documentation.
        </p>
        <div className={styles.heroCtas}>
          <a className={styles.btnPrimary} href="mailto:krusche@tum.de">
            Request a Demo
          </a>
          <Link className={styles.btnGhost} to="/docs/overview/what-is-iris">
            Explore the Docs
          </Link>
        </div>
      </div>
    </section>
  );
}
