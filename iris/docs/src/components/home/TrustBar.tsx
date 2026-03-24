import React from "react";
import styles from "./styles.module.css";

const items = [
  "Integrated into Artemis at TUM",
  "Used across 10+ courses at TUM",
  "MIT Licensed",
  "GDPR Compliant",
];

export default function TrustBar(): React.JSX.Element {
  return (
    <div className={styles.trustBar}>
      {items.map((text) => (
        <span key={text} className={styles.trustItem}>
          <span className={styles.trustDot} aria-hidden="true" />
          {text}
        </span>
      ))}
    </div>
  );
}
