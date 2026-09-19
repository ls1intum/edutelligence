import React from "react";
import Link from "@docusaurus/Link";
import useBaseUrl from "@docusaurus/useBaseUrl";
import styles from "./styles.module.css";

type GuideCard = {
  title: string;
  description: string;
  to: string;
  label: string;
};

const GUIDES: GuideCard[] = [
  {
    title: "User Guide",
    description: "Call the OpenAI-compatible API and use the admin UI.",
    to: "/user/getting-started",
    label: "Get started",
  },
  {
    title: "Administrator Guide",
    description: "Install, configure, and operate a Logos deployment.",
    to: "/admin/installation",
    label: "Deploy Logos",
  },
  {
    title: "Developer Guide",
    description: "Run Logos locally and learn the subsystem layout.",
    to: "/developer/local-setup",
    label: "Develop locally",
  },
];

export default function Homepage(): React.JSX.Element {
  const logo = useBaseUrl("/img/logos-logo.svg");
  const architecture = useBaseUrl("/img/architecture.svg");

  return (
    <div className={styles.page}>
      <section className={styles.hero}>
        <div className={styles.heroInner}>
          <img src={logo} alt="" className={styles.heroLogo} width={72} height={72} />
          <p className={styles.heroBrand}>Logos</p>
          <h1 className={styles.heroHeadline}>LLM engineering made easy</h1>
          <p className={styles.heroSubtitle}>
            OpenAI-compatible inference with logging, billing, policies, and
            self-hosted workers — documented for users, operators, and
            contributors.
          </p>
          <div className={styles.heroCtas}>
            <Link className={styles.btnPrimary} to="/user/getting-started">
              Start with the User Guide
            </Link>
            <Link className={styles.btnGhost} to="/developer/architecture">
              View architecture
            </Link>
          </div>
        </div>
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionHeading}>Choose a guide</h2>
        <p className={styles.sectionSubtitle}>
          Three paths through the same platform — pick the one that matches
          what you are doing today.
        </p>
        <div className={styles.cardGrid}>
          {GUIDES.map((guide) => (
            <Link key={guide.to} className={styles.card} to={guide.to}>
              <h3 className={styles.cardTitle}>{guide.title}</h3>
              <p className={styles.cardBody}>{guide.description}</p>
              <span className={styles.cardCta}>{guide.label} →</span>
            </Link>
          ))}
        </div>
      </section>

      <section className={styles.sectionAlt}>
        <div className={styles.sectionAltInner}>
          <h2 className={styles.sectionHeading}>How Logos fits together</h2>
          <p className={styles.sectionSubtitle}>
            Clients hit one domain. The web service terminates the public
            inference gateway; local and mixed traffic is proxied to the
            orchestrator; workers dial out over WebSocket.
          </p>
          <Link className={styles.diagramLink} to="/developer/architecture">
            <img
              src={architecture}
              alt="Logos architecture diagram showing core node, gateway split, worker nodes, and cloud providers"
              className={styles.diagram}
            />
          </Link>
          <p className={styles.diagramCaption}>
            Full terminology and subsystem tables live in the{" "}
            <Link to="/developer/architecture">architecture reference</Link>.
          </p>
        </div>
      </section>
    </div>
  );
}
