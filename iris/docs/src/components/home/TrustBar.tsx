import React from "react";
import styles from "./styles.module.css";

export default function TrustBar(): React.JSX.Element {
  return (
    <div className={styles.trustBar}>
      <span className={styles.trustItem}>
        <span className={styles.trustDot} aria-hidden="true" />
        Integrated into{" "}
        <a
          href="https://github.com/ls1intum/Artemis"
          target="_blank"
          rel="noopener noreferrer"
          className={styles.trustLink}
        >
          Artemis
        </a>
      </span>
      <span className={styles.trustItem}>
        <span className={styles.trustDot} aria-hidden="true" />
        Used across 10+ courses
      </span>
      <span className={styles.trustItem}>
        <span className={styles.trustDot} aria-hidden="true" />
        MIT Licensed
      </span>
      <span className={styles.trustItem}>
        <span className={styles.trustDot} aria-hidden="true" />
        Built at TU Munich
      </span>
    </div>
  );
}
