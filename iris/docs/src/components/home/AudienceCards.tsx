import React from "react";
import Link from "@docusaurus/Link";
import styles from "./styles.module.css";
import { useFadeIn } from "./useFadeIn";

const audiences = [
  {
    title: "Students",
    description: "Get unstuck on exercises without giving up",
    to: "/docs/student/getting-started",
  },
  {
    title: "Instructors",
    description: "See how students are learning, not just what they submitted",
    to: "/docs/instructor/enabling-iris",
  },
  {
    title: "Developers",
    description: "Extend Iris with new pipelines and tools",
    to: "/docs/developer/local-setup",
  },
  {
    title: "Administrators",
    description: "Deploy on-premise or cloud in under an hour",
    to: "/docs/admin/deployment",
  },
];

const staggerClasses = [
  styles.stagger1,
  styles.stagger2,
  styles.stagger3,
  styles.stagger4,
];

export default function AudienceCards(): React.JSX.Element {
  const [ref, visible] = useFadeIn();

  return (
    <section className={styles.section}>
      <h2 className={styles.sectionHeading}>Who Is Iris For?</h2>
      <p className={styles.sectionSubtitle}>
        Pick the guide that matches your role.
      </p>
      <div
        ref={ref as React.RefObject<HTMLDivElement>}
        className={styles.audienceGrid}
      >
        {audiences.map((a, i) => (
          <Link
            key={a.title}
            className={`${styles.audienceCard} ${styles.fadeIn} ${visible ? styles.fadeInVisible : ""} ${staggerClasses[i] || ""}`}
            to={a.to}
          >
            <div className={styles.audienceCardTitle}>{a.title}</div>
            <div className={styles.audienceCardDesc}>{a.description}</div>
            <div className={styles.audienceCardArrow}>&rarr;</div>
          </Link>
        ))}
      </div>
    </section>
  );
}
