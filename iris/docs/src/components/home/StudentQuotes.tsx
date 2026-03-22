import React from "react";
import styles from "./styles.module.css";
import { useFadeIn } from "./useFadeIn";

const testimonials = [
  {
    initials: "CS",
    text: "It pointed me in the right direction without me even mentioning the algorithm. It was clearly aware of the context.",
    author: "Computer Science Student",
    org: "TU Munich",
  },
  {
    initials: "BI",
    text: "My students stopped asking me the same basic questions. Iris handles those now, and I can focus on deeper discussions in office hours.",
    author: "Biology Instructor",
    org: "TU Munich",
  },
  {
    initials: "MP",
    text: "I was skeptical about AI in education, but Iris actually teaches. It doesn\u2019t just hand out solutions \u2014 it makes students think.",
    author: "Mathematics Professor",
    org: "TU Munich",
  },
  {
    initials: "TA",
    text: "As a TA for 400 students, I can\u2019t answer every question at 2 AM. Iris can \u2014 and it gives the same quality hints I would.",
    author: "Engineering Teaching Assistant",
    org: "TU Munich",
  },
  {
    initials: "IS",
    text: "It\u2019s very easy to learn using ChatGPT. But next day I will forget. Iris made me actually work through problems.",
    author: "Information Systems Student",
    org: "TU Munich",
  },
  {
    initials: "SE",
    text: "What convinced me was the citation feature. When a student gets an answer, they can click through to the actual lecture slide. It\u2019s not a black box.",
    author: "Software Engineering Instructor",
    org: "TU Munich",
  },
];

const staggerClasses = [
  styles.stagger1,
  styles.stagger2,
  styles.stagger3,
  styles.stagger4,
];

export default function StudentQuotes(): React.JSX.Element {
  const [ref, visible] = useFadeIn();

  return (
    <section className={styles.sectionAlt}>
      <div className={styles.sectionAltInner}>
        <h2 className={styles.sectionHeadingAccent}>Trusted by Educators</h2>
        <p className={styles.sectionSubtitle}>
          Iris supports 1,600+ students across multiple disciplines at the
          Technical University of Munich.
        </p>
        <div
          ref={ref as React.RefObject<HTMLDivElement>}
          className={styles.testimonialGrid}
        >
          {testimonials.map((t, i) => (
            <div
              key={t.author}
              className={`${styles.testimonialCard} ${styles.fadeIn} ${visible ? styles.fadeInVisible : ""} ${staggerClasses[i % staggerClasses.length] || ""}`}
            >
              <div className={styles.testimonialHeader}>
                <div className={styles.testimonialAvatar}>{t.initials}</div>
                <div>
                  <div className={styles.testimonialAuthor}>{t.author}</div>
                  <div className={styles.testimonialOrg}>{t.org}</div>
                </div>
              </div>
              <blockquote className={styles.testimonialQuote}>
                {t.text}
              </blockquote>
            </div>
          ))}
        </div>
        <p className={styles.testimonialNote}>
          Perspectives drawn from published research findings (ITiCSE 2024, Koli
          Calling 2025, Computers &amp; Education: AI 2026).
        </p>
      </div>
    </section>
  );
}
