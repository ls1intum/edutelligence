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
      <span aria-hidden="true">🤖</span>
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
        A student is preparing for their biology exam and asks about
        photosynthesis. Here&rsquo;s what happens next.
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
                    Can you explain how photosynthesis works?
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
                    Photosynthesis is the process by which plants convert light
                    energy into chemical energy. It occurs in two stages: the
                    light-dependent reactions and the Calvin cycle&hellip;
                  </div>
                </div>
              </div>
            </div>
            <p className={styles.comparisonOutcome}>
              <span aria-hidden="true">❌</span> Student skims the answer.
              Forgets it tomorrow.
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
                    Can you explain how photosynthesis works?
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
                    Great question! Your instructor covered this on{" "}
                    <strong>slide 7</strong>. Before I explain, what do you
                    already know about how plants capture light energy? Think
                    about what role chlorophyll plays.
                  </div>
                </div>
              </div>
            </div>
            <p
              className={`${styles.comparisonOutcomeGood} ${styles.irisBubble} ${styles.irisBubbleDelay3} ${visible ? styles.irisBubbleVisible : ""}`}
            >
              <span aria-hidden="true">✅</span> Student works through the
              problem. Genuine understanding.
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
