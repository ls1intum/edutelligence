import React from "react";
import Link from "@docusaurus/Link";
import useBaseUrl from "@docusaurus/useBaseUrl";
import styles from "./styles.module.css";

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
            <img
              src={useBaseUrl("/img/screenshots/iris-chat-response-hd.png")}
              alt=""
              className={styles.heroGhostScreenshot}
              width={960}
              height={540}
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
