import React from "react";
import styles from "./styles.module.css";
import { useFadeIn } from "./useFadeIn";

const disciplines = [
  {
    emoji: "\uD83D\uDCBB",
    title: "Computer Science",
    description:
      "Debug code, understand algorithms, and work through programming exercises with context-aware guidance.",
  },
  {
    emoji: "\uD83E\uDDEC",
    title: "Biology & Life Sciences",
    description:
      "Explore lecture concepts from cell biology to ecology with answers grounded in your course slides.",
  },
  {
    emoji: "\uD83D\uDCCA",
    title: "Mathematics & Statistics",
    description:
      "Step through proofs and problem sets with guided hints that build mathematical reasoning.",
  },
  {
    emoji: "\u2696\uFE0F",
    title: "Law & Social Sciences",
    description:
      "Analyze case studies and course readings with citations back to the original materials.",
  },
  {
    emoji: "\u2699\uFE0F",
    title: "Engineering",
    description:
      "Work through design problems, calculations, and lab reports with discipline-specific support.",
  },
  {
    emoji: "\uD83C\uDFAD",
    title: "Humanities & Arts",
    description:
      "Discuss literary analysis, historical arguments, and creative projects using your course framework.",
  },
];

const staggerClasses = [
  styles.stagger1,
  styles.stagger2,
  styles.stagger3,
  styles.stagger4,
];

export default function DisciplinesSection(): React.JSX.Element {
  const [ref, visible] = useFadeIn();

  return (
    <section className={styles.sectionAlt}>
      <div className={styles.sectionAltInner}>
        <h2 className={styles.sectionHeading}>
          Works for Every Course, Every Discipline
        </h2>
        <p className={styles.sectionSubtitle}>
          Iris isn&apos;t just for computer science. Any course that uses
          Artemis can benefit from AI-guided learning &mdash; from biology to
          law.
        </p>
        <div
          ref={ref as React.RefObject<HTMLDivElement>}
          className={styles.disciplineGrid}
        >
          {disciplines.map((d, i) => (
            <div
              key={d.title}
              className={`${styles.disciplineCard} ${styles.fadeIn} ${visible ? styles.fadeInVisible : ""} ${staggerClasses[i % staggerClasses.length] || ""}`}
            >
              <div className={styles.disciplineEmoji} aria-hidden="true">
                {d.emoji}
              </div>
              <h3 className={styles.disciplineTitle}>{d.title}</h3>
              <p className={styles.disciplineDesc}>{d.description}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
