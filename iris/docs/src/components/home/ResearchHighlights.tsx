import React from "react";
import Link from "@docusaurus/Link";
import styles from "./styles.module.css";
import { useFadeIn } from "./useFadeIn";

const stats = [
  { number: "275", label: "students in randomized controlled trial" },
  { number: "+0.55", label: "Cohen\u2019s d increase in intrinsic motivation" },
  { number: "\u22120.81", label: "Cohen\u2019s d reduction in frustration" },
  { number: "3", label: "peer-reviewed publications" },
];

const staggerClasses = [
  styles.stagger1,
  styles.stagger2,
  styles.stagger3,
  styles.stagger4,
];

export default function ResearchHighlights(): React.JSX.Element {
  const [ref, visible] = useFadeIn();

  return (
    <section className={styles.section}>
      <h2 className={styles.sectionHeading}>Research-Backed</h2>
      <p className={styles.sectionSubtitle}>
        Iris is evaluated through rigorous empirical research, not marketing
        claims.
      </p>
      <div
        ref={ref as React.RefObject<HTMLDivElement>}
        className={styles.statsRow}
      >
        {stats.map((s, i) => (
          <div
            key={s.label}
            className={`${styles.statCard} ${styles.fadeIn} ${visible ? styles.fadeInVisible : ""} ${staggerClasses[i] || ""}`}
          >
            <div className={styles.statNumber}>{s.number}</div>
            <div className={styles.statLabel}>{s.label}</div>
          </div>
        ))}
      </div>
      <p className={styles.statsLink}>
        <Link to="/docs/research/publications">Read the research &rarr;</Link>
      </p>
    </section>
  );
}
