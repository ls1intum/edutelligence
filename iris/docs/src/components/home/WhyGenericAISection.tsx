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

interface DifferentiatorRow {
  feature: string;
  chatgpt: boolean;
  iris: boolean;
}

const differentiators: DifferentiatorRow[] = [
  {
    feature: "Broad general knowledge beyond course scope",
    chatgpt: true,
    iris: false,
  },
  {
    feature: "Knows your specific course content",
    chatgpt: false,
    iris: true,
  },
  {
    feature: "Guides with hints instead of giving full answers",
    chatgpt: false,
    iris: true,
  },
  {
    feature: "Cites lecture slides and course materials",
    chatgpt: false,
    iris: true,
  },
  {
    feature: "GDPR compliant & university-hosted",
    chatgpt: false,
    iris: true,
  },
];

export default function WhyGenericAISection(): React.JSX.Element {
  const [ref, visible] = useFadeIn();

  return (
    <section className={styles.section}>
      <h2 className={styles.sectionHeading}>
        Why Generic AI Falls Short for Teaching
      </h2>
      <p className={styles.sectionSubtitle}>
        Generic chatbots give fluent, confident answers &mdash; but they
        don&rsquo;t teach. Without course context or pedagogical design, they
        hand students the answer and skip the learning.
      </p>

      {/* ── Side-by-side chat comparison ── */}
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
        &mdash;&nbsp;research shows a{" "}
        <Link to="/docs/research/publications">
          significant boost in intrinsic motivation
        </Link>{" "}
        (Cohen&rsquo;s <em>d</em>&nbsp;=&nbsp;0.55).
      </p>

      {/* ── Key differentiators ── */}
      <div className={styles.comparisonTableWrapper}>
        <table className={styles.comparisonTable}>
          <thead>
            <tr>
              <th className={styles.comparisonTableFeatureHeader}>Feature</th>
              <th className={styles.comparisonTableHeader}>
                Generic AI Chatbot
              </th>
              <th
                className={`${styles.comparisonTableHeader} ${styles.comparisonTableHeaderIris}`}
              >
                Iris
              </th>
            </tr>
          </thead>
          <tbody>
            {differentiators.map((row) => (
              <tr key={row.feature} className={styles.comparisonTableRow}>
                <td className={styles.comparisonTableFeature}>{row.feature}</td>
                <td className={styles.comparisonTableCell}>
                  <span
                    className={
                      row.chatgpt ? styles.checkMark : styles.crossMark
                    }
                    role="img"
                    aria-label={row.chatgpt ? "Yes" : "No"}
                  >
                    {row.chatgpt ? "\u2713" : "\u2717"}
                  </span>
                </td>
                <td className={styles.comparisonTableCellIris}>
                  <span
                    className={row.iris ? styles.checkMark : styles.crossMark}
                    role="img"
                    aria-label={row.iris ? "Yes" : "No"}
                  >
                    {row.iris ? "\u2713" : "\u2717"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* ── Research quotes ── */}
      <div className={styles.endorseQuotes}>
        <blockquote className={styles.endorseQuote}>
          <p className={styles.endorseQuoteText}>
            &ldquo;If you need to do something fast and efficiently, you would
            use it. But if you do something just for learning, you would
            not.&rdquo;
          </p>
          <cite className={styles.endorseQuoteCite}>
            &mdash; P20, ChatGPT user
          </cite>
        </blockquote>
        <blockquote className={styles.endorseQuote}>
          <p className={styles.endorseQuoteText}>
            &ldquo;I think it&rsquo;s very easy to learn using ChatGPT. But next
            day I will forget because I just learned it from ChatGPT.&rdquo;
          </p>
          <cite className={styles.endorseQuoteCite}>
            &mdash; P20, ChatGPT user
          </cite>
        </blockquote>
      </div>
    </section>
  );
}
