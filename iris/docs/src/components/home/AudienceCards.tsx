import React from "react";
import Link from "@docusaurus/Link";
import styles from "./styles.module.css";

const audiences = [
  {
    title: "Students",
    description: "Learn how to get the most out of Iris",
    to: "/docs/student/getting-started",
  },
  {
    title: "Instructors",
    description: "Configure Iris for your courses",
    to: "/docs/instructor/enabling-iris",
  },
  {
    title: "Developers",
    description: "Contribute to Iris",
    to: "/docs/developer/local-setup",
  },
  {
    title: "Administrators",
    description: "Deploy and operate Iris",
    to: "/docs/admin/deployment",
  },
];

export default function AudienceCards(): React.JSX.Element {
  return (
    <section className={styles.section}>
      <h2 className={styles.sectionHeading}>Jump In</h2>
      <p className={styles.sectionSubtitle}>
        Pick the guide that matches your role.
      </p>
      <div className={styles.audienceGrid}>
        {audiences.map((a) => (
          <Link key={a.title} className={styles.audienceCard} to={a.to}>
            <div className={styles.audienceCardTitle}>{a.title}</div>
            <div className={styles.audienceCardDesc}>{a.description}</div>
            <div className={styles.audienceCardArrow}>&rarr;</div>
          </Link>
        ))}
      </div>
    </section>
  );
}
