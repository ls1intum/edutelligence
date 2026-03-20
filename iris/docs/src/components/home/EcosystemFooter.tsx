import React from "react";
import Link from "@docusaurus/Link";
import styles from "./styles.module.css";

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
  {
    name: "Memiris",
    description:
      "Long-term memory layer enabling Iris to recall past interactions.",
    href: "https://github.com/ls1intum/edutelligence",
    external: true,
  },
  {
    name: "Atlas",
    description:
      "Competency management and learning path recommendation system.",
    href: "https://github.com/ls1intum/Artemis",
    external: true,
  },
  {
    name: "Nebula",
    description: "Adaptive exercise generation powered by knowledge graphs.",
    href: "https://github.com/ls1intum/edutelligence",
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

export default function EcosystemFooter(): React.JSX.Element {
  return (
    <section className={styles.section}>
      <h2 className={styles.sectionHeading}>The EduTelligence Ecosystem</h2>
      <p className={styles.sectionSubtitle}>
        Iris is part of a broader family of AI-powered education tools.
      </p>
      <div className={styles.ecosystemGrid}>
        {ecosystem.map((item) =>
          item.external ? (
            <a
              key={item.name}
              className={styles.ecosystemCard}
              href={item.href}
              target="_blank"
              rel="noopener noreferrer"
            >
              <CardContent item={item} />
            </a>
          ) : (
            <Link
              key={item.name}
              className={styles.ecosystemCard}
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
