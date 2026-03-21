import React from "react";
import styles from "./styles.module.css";
import { useFadeIn } from "./useFadeIn";

const stats = [
  {
    number: "1,655",
    label: "Students",
    detail: "Across 3 courses at TU Munich in Winter 2025/26",
  },
  {
    number: "11,400+",
    label: "Conversations",
    detail: "In-depth exchanges with 10 or more messages each",
  },
  {
    number: "3",
    label: "Published Studies",
    detail: "Peer-reviewed at ITiCSE 2024, Koli Calling 2025, and C&E:AI 2026",
  },
];

const staggerClasses = [styles.stagger1, styles.stagger2, styles.stagger3];

export default function ScaleSection(): React.JSX.Element {
  const [ref, visible] = useFadeIn();

  return (
    <section className={styles.sectionAlt}>
      <div className={styles.sectionAltInner}>
        <h2 className={styles.sectionHeading}>Built for Scale</h2>
        <p className={styles.sectionSubtitle}>
          Iris isn&apos;t a prototype. It&apos;s a production system supporting
          thousands of students across one of Europe&apos;s largest technical
          universities.
        </p>
        <div
          ref={ref as React.RefObject<HTMLDivElement>}
          className={styles.scaleGrid}
        >
          {stats.map((stat, i) => (
            <div
              key={stat.label}
              className={`${styles.scaleCard} ${styles.fadeIn} ${visible ? styles.fadeInVisible : ""} ${staggerClasses[i] || ""}`}
            >
              <div className={styles.scaleNumber}>{stat.number}</div>
              <div className={styles.scaleLabel}>{stat.label}</div>
              <div className={styles.scaleDetail}>{stat.detail}</div>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
