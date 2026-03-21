import React from "react";
import Link from "@docusaurus/Link";
import useBaseUrl from "@docusaurus/useBaseUrl";
import styles from "./styles.module.css";
import { useFadeIn } from "./useFadeIn";

export default function ClosingCta(): React.JSX.Element {
  const [ref, visible] = useFadeIn();

  return (
    <section className={styles.closingCtaWrapper}>
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
          Ready to bring Iris to your university?
        </h2>
        <p className={styles.closingCtaSubtitle}>
          Deployment takes under an hour. We&rsquo;ll walk you through setup,
          integration, and your first course &mdash; no commitment required.
        </p>
        <div className={styles.heroCtas}>
          <Link className={styles.btnPrimary} to="mailto:krusche@tum.de">
            Request a Demo
          </Link>
          <Link className={styles.btnGhost} to="/docs/overview/what-is-iris">
            Explore the Docs
          </Link>
        </div>
      </div>
    </section>
  );
}
