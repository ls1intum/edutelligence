import React from "react";
import styles from "./styles.module.css";
import { useFadeIn } from "./useFadeIn";

const testimonials = [
  {
    id: "P19",
    text: "Iris was clearly aware of the context. It pointed me in the right direction. When I asked for getting the strings, it said, you can shift the strings like this for this algorithm without me even mentioning the algorithm.",
    condition: "Iris user",
  },
];

export default function StudentQuotes(): React.JSX.Element {
  const [ref, visible] = useFadeIn();

  return (
    <section className={styles.sectionAlt}>
      <div className={styles.sectionAltInner}>
        <h2 className={styles.sectionHeadingAccent}>
          What Students Say About Iris
        </h2>
        <p className={styles.sectionSubtitle}>
          Verbatim from qualitative interviews in a controlled study comparing
          Iris, ChatGPT, and no-AI support across 33 CS students.
        </p>
        <div
          ref={ref as React.RefObject<HTMLDivElement>}
          className={styles.testimonialGrid}
        >
          {testimonials.map((t, i) => (
            <div
              key={`${t.id}-${i}`}
              className={`${styles.testimonialCard} ${styles.fadeIn} ${visible ? styles.fadeInVisible : ""} ${styles.stagger1}`}
            >
              <div className={styles.testimonialHeader}>
                <div className={styles.testimonialAvatar}>{t.id}</div>
                <div>
                  <div className={styles.testimonialAuthor}>
                    Participant {t.id}
                  </div>
                  <div className={styles.testimonialOrg}>
                    {t.condition}, Koli Calling 2025
                  </div>
                </div>
              </div>
              <blockquote className={styles.testimonialQuote}>
                &ldquo;{t.text}&rdquo;
              </blockquote>
            </div>
          ))}
        </div>
        <p className={styles.testimonialNote}>
          Verbatim quote from Bassner, Lottner &amp; Krusche (2025).
          &ldquo;Towards Understanding the Impact of Context-Aware AI Tutors and
          General-Purpose AI Chatbots on Student Learning.&rdquo; Koli Calling
          &apos;25, ACM.
        </p>
      </div>
    </section>
  );
}
