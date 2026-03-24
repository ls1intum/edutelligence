import React from "react";
import Link from "@docusaurus/Link";
import styles from "./styles.module.css";
import { useFadeIn } from "./useFadeIn";

const scaleStats = [
  {
    number: "1,600+",
    label: "Students Supported",
    detail: "In a single semester at TU Munich",
  },
  {
    number: "30,000+",
    label: "Conversations Powered",
    detail: "Real student interactions with Iris",
  },
  {
    number: "3",
    label: "Published Studies",
    detail: "Peer-reviewed at top computing education venues",
  },
];

const papers = [
  {
    venue: "ITiCSE 2024",
    date: "July 2024",
    title: "Iris: An AI-Driven Virtual Tutor for Computer Science Education",
    finding:
      "Students perceive Iris as effective, providing relevant support while serving as a complement to human tutors.",
  },
  {
    venue: "Koli Calling 2025",
    date: "November 2025",
    title:
      "Towards Understanding the Impact of Context-Aware AI Tutors and General-Purpose AI Chatbots on Student Learning",
    finding:
      "Context awareness universally valued; ChatGPT users expressed stronger over-reliance concerns than Iris users.",
  },
  {
    venue: "Computers & Education: AI, Vol 10, 2026",
    date: "December 2025",
    title: "Less Stress, Better Scores, Same Learning",
    finding:
      "Both AI tools improved scores, but only Iris enhanced intrinsic motivation. ChatGPT created a \u201Ccomfort trap\u201D of perceived helpfulness without learning gains.",
  },
];

const staggerClasses = [styles.stagger1, styles.stagger2, styles.stagger3];

export default function EvidenceSection(): React.JSX.Element {
  const [statsRef, statsVisible] = useFadeIn();
  const [papersRef, papersVisible] = useFadeIn();

  return (
    <section id="evidence" className={styles.sectionScaleBg}>
      <div className={styles.sectionScaleInner}>
        <h2 className={styles.sectionHeadingAccent}>
          Used at Scale. Studied in Real Courses.
        </h2>
        <p className={styles.sectionSubtitle}>
          Iris is not a prototype. It has been deployed and evaluated in live
          teaching at the Technical University of Munich.
        </p>

        {/* Part 1: Scale stats */}
        <div
          ref={statsRef as React.RefObject<HTMLDivElement>}
          className={styles.scaleGrid}
        >
          {scaleStats.map((stat, i) => (
            <div
              key={stat.label}
              className={`${styles.scaleCard} ${styles.fadeIn} ${statsVisible ? styles.fadeInVisible : ""} ${staggerClasses[i] || ""}`}
            >
              <div className={styles.scaleNumber}>{stat.number}</div>
              <div className={styles.scaleLabel}>{stat.label}</div>
              <div className={styles.scaleDetail}>{stat.detail}</div>
            </div>
          ))}
        </div>

        {/* Part 2: Research papers */}
        <p className={styles.quoteGridLabel}>Key Research Findings</p>
        <div
          ref={papersRef as React.RefObject<HTMLDivElement>}
          className={styles.scaleGrid}
        >
          {papers.map((paper, i) => (
            <div
              key={paper.venue}
              className={`${styles.scaleCard} ${styles.fadeIn} ${papersVisible ? styles.fadeInVisible : ""} ${staggerClasses[i] || ""}`}
              style={{ textAlign: "left" }}
            >
              <div className={styles.scaleLabel}>{paper.venue}</div>
              <div
                className={styles.scaleDetail}
                style={{ marginBottom: "0.75rem", fontStyle: "italic" }}
              >
                {paper.title}
              </div>
              <div className={styles.scaleDetail}>
                <strong>Key finding:</strong> {paper.finding}
              </div>
            </div>
          ))}
        </div>

        <p className={styles.statsLink}>
          <Link to="/docs/research/publications">Read the research &rarr;</Link>
        </p>
      </div>
    </section>
  );
}
