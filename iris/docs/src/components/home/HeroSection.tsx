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
            My recursive method keeps returning null. Can you just fix it?
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
            Let&apos;s figure this out together. What should your base case
            return when the list is empty? Check{" "}
            <strong>exercise 5, task 2</strong> for a hint.{" "}
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
            AI That <em>Teaches</em>, Not Just Answers
          </h1>
          <p className={styles.heroSubtitle}>
            Grounded in your course materials. Built into Artemis. Backed by 3
            peer-reviewed studies.
          </p>
          <p className={styles.heroProof}>
            <span aria-hidden="true">🎓</span> 30,000+ conversations powered at
            TU Munich
          </p>
          <div className={styles.heroCtas}>
            <a className={styles.btnPrimary} href="mailto:krusche@tum.de">
              Request a Demo
            </a>
            <Link className={styles.btnGhost} to="/docs/research/publications">
              Read the Research
            </Link>
          </div>
        </header>
        <div className={styles.heroVisual}>
          <div className={styles.heroVisualInner}>
            <ChatMockup />
          </div>
        </div>
      </div>
    </div>
  );
}
