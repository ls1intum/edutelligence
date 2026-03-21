import React from "react";
import Link from "@docusaurus/Link";
import styles from "./styles.module.css";
import { useFadeIn } from "./useFadeIn";

const stats = [
  {
    number: "275",
    label: "students",
    subtitle: "in a randomized controlled trial",
  },
  {
    number: "+0.55",
    label: "effect size",
    subtitle: "significantly more motivated",
  },
  {
    number: "\u22120.81",
    label: "effect size",
    subtitle: "dramatically less frustrated",
  },
  {
    number: "3",
    label: "papers",
    subtitle: "peer-reviewed and published",
  },
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
        Results from a randomized controlled trial with 275 students at TU
        Munich.
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
            <div className={styles.statSubtitle}>{s.subtitle}</div>
          </div>
        ))}
      </div>
      <p className={styles.statsLink}>
        <Link to="/docs/research/publications">Read the research &rarr;</Link>
      </p>
    </section>
  );
}
