import React from "react";
import styles from "./styles.module.css";
import { useFadeIn } from "./useFadeIn";

const memoryChips = [
  "Prefers visual explanations",
  "Struggled with recursion",
  "Strong in databases",
  "Learns best with examples",
  "Reviewed linked lists twice",
  "Prefers step-by-step",
];

const staggerClasses = [
  styles.stagger1,
  styles.stagger2,
  styles.stagger3,
  styles.stagger4,
];

export default function MemorySection(): React.JSX.Element {
  const [ref, visible] = useFadeIn();

  return (
    <section className={styles.section}>
      <h2 className={styles.sectionHeading}>
        Gets Smarter the More You Use It
      </h2>
      <p className={styles.sectionSubtitle}>
        Iris remembers your learning style, past questions, and progress. Unlike
        generic chatbots, every conversation builds on the last.
      </p>
      <div
        ref={ref as React.RefObject<HTMLDivElement>}
        className={`${styles.memoryGrid} ${styles.fadeIn} ${visible ? styles.fadeInVisible : ""}`}
      >
        {memoryChips.map((chip, i) => (
          <span
            key={chip}
            className={`${styles.memoryChip} ${staggerClasses[i % staggerClasses.length] || ""}`}
          >
            {chip}
          </span>
        ))}
      </div>
    </section>
  );
}
