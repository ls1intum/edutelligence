import React from "react";
import Link from "@docusaurus/Link";
import useBaseUrl from "@docusaurus/useBaseUrl";
import styles from "./styles.module.css";
import { useFadeIn } from "./useFadeIn";

function StudentAvatar({ className }: { className?: string }) {
  return <div className={`${styles.chatUIAvatar} ${className || ""}`}>S</div>;
}

function BotAvatar({ className }: { className?: string }) {
  return (
    <div
      className={`${styles.chatUIAvatar} ${styles.chatUIAvatarBot} ${className || ""}`}
    >
      🤖
    </div>
  );
}

function IrisAvatar() {
  const logoUrl = useBaseUrl("/img/iris/iris-logo-big-right.png");
  return (
    <div className={`${styles.chatUIAvatar} ${styles.chatUIAvatarIris}`}>
      <img src={logoUrl} alt="" className={styles.chatUIAvatarImg} />
    </div>
  );
}

export default function ComparisonSection(): React.JSX.Element {
  const [ref, visible] = useFadeIn();

  return (
    <section id="comparison" className={styles.section}>
      <h2 className={styles.sectionHeading}>How Iris Is Different</h2>
      <p className={styles.sectionSubtitle}>
        A student is stuck on the Burrows&ndash;Wheeler Transform rotation step.
        Here&rsquo;s what happens next.
      </p>
      <div
        ref={ref as React.RefObject<HTMLDivElement>}
        className={`${styles.comparisonWrapper} ${styles.fadeIn} ${visible ? styles.fadeInVisible : ""}`}
      >
        <div className={styles.comparisonGrid}>
          {/* ── Generic Chatbot ── */}
          <div className={styles.comparisonColGeneric}>
            <span
              className={`${styles.comparisonLabel} ${styles.labelGeneric}`}
            >
              Generic Chatbot
            </span>
            <div className={styles.chatUIThread}>
              <div className={styles.chatUIMessage}>
                <StudentAvatar />
                <div className={styles.chatUIMessageContent}>
                  <div className={styles.chatUIMessageHeader}>
                    <span className={styles.chatUIMessageName}>Student</span>
                    <span className={styles.chatUIMessageTime}>14:32</span>
                  </div>
                  <div className={styles.chatUIBubbleLeft}>
                    How do I do the BWT rotation step?
                  </div>
                </div>
              </div>
              <div className={styles.chatUIMessage}>
                <BotAvatar />
                <div className={styles.chatUIMessageContent}>
                  <div className={styles.chatUIMessageHeader}>
                    <span className={styles.chatUIMessageName}>ChatGPT</span>
                    <span className={styles.chatUIMessageTime}>14:32</span>
                  </div>
                  <div className={styles.chatUIBubbleLeft}>
                    Sure! Here&rsquo;s the full implementation:{" "}
                    <code>
                      rotations = [s[i:] + s[:i] for i in range(len(s))]
                    </code>
                    <br />
                    <code>table = sorted(rotations); ...</code>
                  </div>
                </div>
              </div>
            </div>
            <p className={styles.comparisonOutcome}>
              ❌ Student copies the answer. Learns nothing.
            </p>
          </div>

          {/* ── Iris ── */}
          <div className={styles.comparisonColIris}>
            <span className={`${styles.comparisonLabel} ${styles.labelIris}`}>
              Iris
            </span>
            <div className={styles.chatUIThread}>
              <div
                className={`${styles.chatUIMessage} ${styles.irisBubble} ${styles.irisBubbleDelay1} ${visible ? styles.irisBubbleVisible : ""}`}
              >
                <StudentAvatar />
                <div className={styles.chatUIMessageContent}>
                  <div className={styles.chatUIMessageHeader}>
                    <span className={styles.chatUIMessageName}>Student</span>
                    <span className={styles.chatUIMessageTime}>14:32</span>
                  </div>
                  <div className={styles.chatUIBubbleLeft}>
                    How do I do the BWT rotation step?
                  </div>
                </div>
              </div>
              <div
                className={`${styles.chatUIMessage} ${styles.irisBubble} ${styles.irisBubbleDelay2} ${visible ? styles.irisBubbleVisible : ""}`}
              >
                <IrisAvatar />
                <div className={styles.chatUIMessageContent}>
                  <div className={styles.chatUIMessageHeader}>
                    <span className={styles.chatUIMessageNameIris}>Iris</span>
                    <span className={styles.chatUIMessageTime}>14:33</span>
                  </div>
                  <div className={styles.chatUIBubbleIris}>
                    I see you&rsquo;re working on the BWT rotation step. Think
                    about what happens when you rotate a string by moving the
                    first character to the end. Can you see how to generate all
                    rotations from there?
                  </div>
                </div>
              </div>
            </div>
            <p
              className={`${styles.comparisonOutcomeGood} ${styles.irisBubble} ${styles.irisBubbleDelay3} ${visible ? styles.irisBubbleVisible : ""}`}
            >
              ✅ Student works through the problem. Genuine understanding.
            </p>
          </div>
        </div>
      </div>
      <p
        className={`${styles.comparisonTakeaway} ${styles.irisBubble} ${styles.irisBubbleDelay4} ${visible ? styles.irisBubbleVisible : ""}`}
      >
        Iris guides students to the answer instead of giving it away
        &mdash;&nbsp;that&rsquo;s why they learn{" "}
        <Link to="/docs/research/publications">55% more effectively</Link>.
      </p>
    </section>
  );
}
