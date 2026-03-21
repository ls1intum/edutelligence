import React from "react";
import Link from "@docusaurus/Link";
import styles from "./styles.module.css";
import { useFadeIn } from "./useFadeIn";

interface EcosystemItem {
  name: string;
  description: string;
  href: string;
  highlight?: boolean;
  external?: boolean;
}

const ecosystem: EcosystemItem[] = [
  {
    name: "Iris",
    description: "AI virtual tutor providing scaffolded guidance for students.",
    href: "/docs/overview/what-is-iris",
    highlight: true,
    external: false,
  },
  {
    name: "Artemis",
    description:
      "Interactive learning platform with instant feedback on exercises.",
    href: "https://github.com/ls1intum/Artemis",
    external: true,
  },
  {
    name: "Athena",
    description:
      "AI-powered assessment engine for automated and semi-automated grading.",
    href: "https://github.com/ls1intum/Athena",
    external: true,
  },
];

function CardContent({ item }: { item: EcosystemItem }): React.JSX.Element {
  return (
    <>
      <div
        className={
          item.highlight
            ? styles.ecosystemCardHighlight
            : styles.ecosystemCardName
        }
      >
        {item.name}
      </div>
      <div className={styles.ecosystemCardDesc}>{item.description}</div>
    </>
  );
}

const staggerClasses = [
  styles.stagger1,
  styles.stagger2,
  styles.stagger3,
  styles.stagger4,
];

export default function EcosystemFooter(): React.JSX.Element {
  const [ref, visible] = useFadeIn();

  return (
    <section className={styles.section}>
      <h2 className={styles.sectionHeading}>The EduTelligence Ecosystem</h2>
      <p className={styles.sectionSubtitle}>
        Iris is part of a broader family of AI-powered education tools.
      </p>
      <div
        ref={ref as React.RefObject<HTMLDivElement>}
        className={styles.ecosystemGrid}
      >
        {ecosystem.map((item, i) =>
          item.external ? (
            <a
              key={item.name}
              className={`${styles.ecosystemCard} ${styles.fadeIn} ${visible ? styles.fadeInVisible : ""} ${staggerClasses[i % staggerClasses.length] || ""}`}
              href={item.href}
              target="_blank"
              rel="noopener noreferrer"
            >
              <CardContent item={item} />
            </a>
          ) : (
            <Link
              key={item.name}
              className={`${styles.ecosystemCard} ${styles.fadeIn} ${visible ? styles.fadeInVisible : ""} ${staggerClasses[i % staggerClasses.length] || ""}`}
              to={item.href}
            >
              <CardContent item={item} />
            </Link>
          ),
        )}
      </div>
    </section>
  );
}
