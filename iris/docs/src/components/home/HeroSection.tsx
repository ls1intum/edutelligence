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
            How do I implement the BWT rotation step?
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
            Think about what happens when you take a string like{" "}
            <code>BANANA$</code> and rotate it one position. What pattern do you
            see? <span className={styles.chatTypingDots}>...</span>
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
            The AI tutor that teaches, not just <em>answers</em>
          </h1>
          <p className={styles.heroSubtitle}>
            An AI tutor built into Artemis, grounded in course materials, and
            backed by peer-reviewed research at TU Munich.
          </p>
          <p className={styles.heroProof}>
            Used by 1,600+ students at TU Munich in Winter 2025/26
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
          <ChatMockup />
        </div>
      </div>
    </div>
  );
}
