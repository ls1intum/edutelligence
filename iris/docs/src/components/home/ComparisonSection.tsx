import React from "react";
import styles from "./styles.module.css";
import { useFadeIn } from "./useFadeIn";

export default function ComparisonSection(): React.JSX.Element {
  const [ref, visible] = useFadeIn();

  return (
    <section className={styles.sectionAlt}>
      <div className={styles.sectionAltInner}>
        <h2 className={styles.sectionHeading}>How Iris Is Different</h2>
        <p className={styles.sectionSubtitle}>
          A student is stuck on the Burrows&ndash;Wheeler Transform rotation
          step. Here&rsquo;s what happens next.
        </p>
        <div
          ref={ref as React.RefObject<HTMLDivElement>}
          className={`${styles.comparisonWrapper} ${styles.fadeIn} ${visible ? styles.fadeInVisible : ""}`}
        >
          <div className={styles.comparisonGrid}>
            {/* ── Generic Chatbot ── */}
            <div className={styles.comparisonColGeneric}>
              <span
                className={`${styles.comparisonLabel} ${styles.labelGeneric}`}
              >
                Generic Chatbot
              </span>
              <div className={styles.comparisonBubble}>
                <strong>Student:</strong> How do I do the BWT rotation step?
              </div>
              <div className={styles.comparisonBubble}>
                <strong>Chatbot:</strong> Here&rsquo;s the solution for the BWT
                rotation: <code>sorted(rotations)</code>
              </div>
              <p className={styles.comparisonOutcome}>
                Student copies the answer. Learns nothing.
              </p>
            </div>

            {/* ── Iris ── */}
            <div className={styles.comparisonColIris}>
              <span className={`${styles.comparisonLabel} ${styles.labelIris}`}>
                Iris
              </span>
              <div className={styles.comparisonBubble}>
                <strong>Student:</strong> How do I do the BWT rotation step?
              </div>
              <div className={styles.comparisonBubble}>
                <strong>Iris:</strong> I see you&rsquo;re working on the BWT
                rotation step. Think about what happens when you rotate a string
                by moving the first character to the end. Can you see how to
                generate all rotations from there?
              </div>
              <p className={styles.comparisonOutcomeGood}>
                Student works through the problem. Genuine understanding.
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
