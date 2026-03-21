import React from "react";
import Link from "@docusaurus/Link";
import useBaseUrl from "@docusaurus/useBaseUrl";
import styles from "./styles.module.css";

function SparkleIcon(): React.JSX.Element {
  return (
    <svg
      className={styles.heroSparkle}
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <path
        d="M12 2L14.09 8.26L20 9.27L15.55 13.97L16.91 20L12 16.9L7.09 20L8.45 13.97L4 9.27L9.91 8.26L12 2Z"
        fill="rgba(42,115,180,0.7)"
        stroke="rgba(42,115,180,0.9)"
        strokeWidth="1"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ChatMockup(): React.JSX.Element {
  return (
    <div className={styles.chatMockup} aria-hidden="true">
      <div className={styles.chatMockupHeader}>
        <div className={styles.chatMockupDots}>
          <span className={styles.chatMockupDotRed} />
          <span className={styles.chatMockupDotYellow} />
          <span className={styles.chatMockupDotGreen} />
        </div>
        <span className={styles.chatMockupTitle}>Iris Chat</span>
      </div>
      <div className={styles.chatMockupBody}>
        <div className={styles.chatBubbleUser}>
          <div className={styles.chatAvatar}>S</div>
          <div className={styles.chatBubbleContent}>
            Can you explain what photosynthesis does?
          </div>
        </div>
        <div className={styles.chatBubbleIris}>
          <div className={styles.chatAvatarIris}>
            <img
              src={useBaseUrl("/img/iris/iris-logo-big-right.png")}
              alt=""
              className={styles.chatAvatarImg}
            />
            <SparkleIcon />
          </div>
          <div className={styles.chatBubbleContentIris}>
            Good question! Before I explain, what do you already know about how
            plants get their energy? Your instructor covered this on{" "}
            <strong>slide 7</strong> with a great diagram.{" "}
            <span className={styles.chatCitation}>[1]</span>{" "}
            <span className={styles.chatTypingDots}>...</span>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function HeroSection(): React.JSX.Element {
  return (
    <div className={styles.heroWrapper}>
      <div className={styles.heroSplit}>
        <header className={styles.hero}>
          <img
            src={useBaseUrl("/img/iris/iris-logo-big-right.png")}
            alt="Iris mascot"
            className={styles.heroLogo}
          />
          <h1 className={styles.heroHeadline}>
            Your AI Teaching Assistant &mdash; Grounded in Your{" "}
            <em>Course Materials</em>
          </h1>
          <p className={styles.heroSubtitle}>
            The AI teaching assistant built into Artemis. Guides students with
            hints &mdash; not answers. Backed by 3 peer-reviewed studies at TU
            Munich.
          </p>
          <p className={styles.heroProof}>
            <span aria-hidden="true">🎓</span> Used by 1,600+ students at TU
            Munich in Winter 2025/26
          </p>
          <div className={styles.heroCtas}>
            <a className={styles.btnPrimary} href="#comparison">
              See How It Works
            </a>
            <Link className={styles.btnGhost} to="/docs/research/publications">
              Read the Research
            </Link>
          </div>
        </header>
        <div className={styles.heroVisual}>
          <div className={styles.heroVisualInner}>
            {/* Floating decorative elements */}
            <div
              className={`${styles.heroFloatingChip} ${styles.heroFloatCitation}`}
              aria-hidden="true"
            >
              <span className={styles.heroFloatCitationBracket}>[</span>slide 7
              <span className={styles.heroFloatCitationBracket}>]</span>
            </div>
            <div
              className={`${styles.heroFloatingChip} ${styles.heroFloatThinking}`}
              aria-hidden="true"
            >
              <span className={styles.heroFloatThinkingLabel}>thinking</span>
              <span className={styles.heroFloatThinkingDots}>
                <span className={styles.heroFloatDot} />
                <span className={styles.heroFloatDot} />
                <span className={styles.heroFloatDot} />
              </span>
            </div>
            <div
              className={`${styles.heroFloatingChip} ${styles.heroFloatHelpful}`}
              aria-hidden="true"
            >
              <svg
                width="12"
                height="12"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <polyline points="20 6 9 17 4 12" />
              </svg>
              94% helpful
            </div>
            <img
              src={useBaseUrl("/img/screenshots/iris-chat-response-hd.png")}
              alt=""
              className={styles.heroGhostScreenshot}
              aria-hidden="true"
              loading="lazy"
            />
            <ChatMockup />
          </div>
        </div>
      </div>
    </div>
  );
}
