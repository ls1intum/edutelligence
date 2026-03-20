import React from "react";
import styles from "./styles.module.css";

export default function StudentQuotes(): React.JSX.Element {
  return (
    <section className={styles.section}>
      <div className={styles.quoteBlock}>
        <p className={styles.quoteText}>
          Iris was clearly aware of the context. It pointed me in the right
          direction. When I asked for getting the strings, it said, you can
          shift the strings like this for this algorithm without me even
          mentioning the algorithm.
        </p>
        <p className={styles.quoteAttribution}>
          &mdash; P19, Koli Calling qualitative study
        </p>
      </div>
    </section>
  );
}
