import React from "react";
import Link from "@docusaurus/Link";
import styles from "./styles.module.css";
import { useFadeIn } from "./useFadeIn";

const paths = [
  {
    title: "Launch in a Course",
    description:
      "Already on Artemis? Upload your slides and enable Iris in minutes. New to Artemis? It's open-source and free to deploy.",
    to: "/docs/instructor/enabling-iris",
  },
  {
    title: "Use Iris in Artemis",
    description:
      "Open the Iris chat inside any programming exercise or course. Ask questions, get hints grounded in your course materials.",
    to: "/docs/student/getting-started",
  },
  {
    title: "Read the Research",
    description:
      "Explore the peer-reviewed studies behind Iris, contribute to the open-source project, or collaborate with the team at TUM.",
    to: "/docs/research/publications",
  },
];

const staggerClasses = [styles.stagger1, styles.stagger2, styles.stagger3];

export default function AudienceCards(): React.JSX.Element {
  const [ref, visible] = useFadeIn();

  return (
    <section className={styles.section}>
      <h2 className={styles.sectionHeading}>Choose Your Starting Point</h2>
      <div
        ref={ref as React.RefObject<HTMLDivElement>}
        className={styles.audienceGrid}
      >
        {paths.map((a, i) => (
          <Link
            key={a.title}
            className={`${styles.audienceCard} ${styles.fadeIn} ${visible ? styles.fadeInVisible : ""} ${staggerClasses[i] || ""}`}
            to={a.to}
          >
            <div className={styles.audienceCardTitle}>{a.title}</div>
            <div className={styles.audienceCardDesc}>{a.description}</div>
            <div className={styles.audienceCardArrow} aria-hidden="true">
              &rarr;
            </div>
          </Link>
        ))}
      </div>
    </section>
  );
}
