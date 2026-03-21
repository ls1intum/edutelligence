import React from "react";
import styles from "./styles.module.css";
import { useFadeIn } from "./useFadeIn";

export default function ComfortTrapSection(): React.JSX.Element {
  const [ref, visible] = useFadeIn();

  return (
    <section className={styles.sectionAmber}>
      <h2 className={styles.sectionHeading}>
        The Comfort Trap: Why &ldquo;Easier&rdquo; Isn&apos;t Always Better
      </h2>
      <p className={styles.sectionSubtitle}>
        Students prefer tools that feel effortless. But the research shows that
        feeling is misleading.
      </p>
      <div
        ref={ref as React.RefObject<HTMLDivElement>}
        className={`${styles.comfortTrapContent} ${styles.fadeIn} ${visible ? styles.fadeInVisible : ""}`}
      >
        <div className={styles.comfortTrapBody}>
          <p>
            In a <strong>275-student randomized controlled trial</strong>,
            students consistently rated ChatGPT as more helpful and easier to
            use than Iris. But here&apos;s the twist: ChatGPT produced{" "}
            <strong>no motivational benefit</strong> and created what
            researchers call a <em>comfort trap</em>.
          </p>
          <p>
            Students felt they were learning more, but they were actually just
            completing tasks faster. Iris takes a deliberately different
            approach: instead of giving you the answer, it gives you a hint
            &mdash; a question that points you toward the solution.
          </p>
          <p>
            This feels harder in the moment. But it preserves{" "}
            <strong>productive struggle</strong> &mdash; the kind of mental
            effort that actually builds understanding. The result? Iris was the{" "}
            <strong>only tool that increased intrinsic motivation</strong>{" "}
            &mdash; students didn&apos;t just finish their work, they wanted to
            keep going.
          </p>
        </div>
        <p className={styles.quoteGridLabel}>
          What students say about generic AI tools
        </p>
        <div className={styles.quoteGrid}>
          <blockquote className={styles.quoteCard}>
            <p className={styles.quoteCardText}>
              &ldquo;In my experience, I have seen that a part of your brain
              turns off when you are basically telling the AI to do the
              stuff.&rdquo;
            </p>
            <cite className={styles.quoteCardCite}>
              &mdash; Student P22 (Control group), Koli Calling 2025
            </cite>
          </blockquote>
          <blockquote className={styles.quoteCard}>
            <p className={styles.quoteCardText}>
              &ldquo;I think it is very easy to learn using ChatGPT. But next
              day I will forget because I just learned it from ChatGPT.&rdquo;
            </p>
            <cite className={styles.quoteCardCite}>
              &mdash; Student P20 (ChatGPT group), Koli Calling 2025
            </cite>
          </blockquote>
        </div>
        <div className={styles.comfortTrapCallout}>
          <h3 className={styles.comfortTrapCalloutTitle}>
            What is productive struggle?
          </h3>
          <p className={styles.comfortTrapCalloutText}>
            Productive struggle is the sweet spot between frustration and
            boredom. It&apos;s what happens when a problem is challenging enough
            to make you think, but not so hard that you give up. Good teaching
            keeps students in this zone. Iris is designed to do the same.
          </p>
        </div>
      </div>
    </section>
  );
}
