import React from "react";
import Link from "@docusaurus/Link";
import styles from "./styles.module.css";

const stats = [
  { number: "275", label: "students in randomized controlled trial" },
  { number: "+0.55", label: "Cohen\u2019s d increase in intrinsic motivation" },
  { number: "\u22120.81", label: "Cohen\u2019s d reduction in frustration" },
  { number: "3", label: "peer-reviewed publications" },
];

export default function ResearchHighlights(): React.JSX.Element {
  return (
    <section className={styles.section}>
      <h2 className={styles.sectionHeading}>Research-Backed</h2>
      <p className={styles.sectionSubtitle}>
        Iris is evaluated through rigorous empirical research, not marketing
        claims.
      </p>
      <div className={styles.statsRow}>
        {stats.map((s) => (
          <div key={s.label} className={styles.statCard}>
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
