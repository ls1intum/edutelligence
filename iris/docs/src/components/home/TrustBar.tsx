import React from "react";
import styles from "./styles.module.css";

const items = [
  "Integrated into Artemis at TUM",
  "1,600+ active students",
  "Open Source",
  "Peer-Reviewed Research",
];

export default function TrustBar(): React.JSX.Element {
  return (
    <div className={styles.trustBar}>
      {items.map((text) => (
        <span key={text} className={styles.trustItem}>
          <span className={styles.trustDot} />
          {text}
        </span>
      ))}
    </div>
  );
}
