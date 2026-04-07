import React, { useEffect, useState } from "react";
import styles from "./styles.module.css";

const sections = [
  { id: "how-it-works", label: "How It Works" },
  { id: "evidence", label: "Evidence" },
  { id: "privacy", label: "Privacy" },
  { id: "faq", label: "FAQ" },
  { id: "demo", label: "Demo" },
];

export default function SectionNav(): React.JSX.Element {
  const [activeId, setActiveId] = useState<string>("");
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setActiveId(entry.target.id);
          }
        }
      },
      { rootMargin: "-40% 0px -40% 0px" },
    );

    const heroEl = document.querySelector("[class*='heroWrapper']");

    // Show/hide nav based on scroll past hero
    const scrollObserver = new IntersectionObserver(
      ([entry]) => setVisible(!entry.isIntersecting),
      { threshold: 0 },
    );
    if (heroEl) scrollObserver.observe(heroEl);

    // Observe each target section
    for (const s of sections) {
      const el = document.getElementById(s.id);
      if (el) observer.observe(el);
    }

    return () => {
      observer.disconnect();
      scrollObserver.disconnect();
    };
  }, []);

  return (
    <nav
      className={`${styles.sectionNav} ${visible ? styles.sectionNavVisible : ""}`}
      aria-label="Page sections"
    >
      {sections.map((s) => (
        <a
          key={s.id}
          href={`#${s.id}`}
          className={`${styles.sectionNavItem} ${activeId === s.id ? styles.sectionNavItemActive : ""}`}
          title={s.label}
        >
          <span className={styles.sectionNavDot} />
          <span className={styles.sectionNavLabel}>{s.label}</span>
        </a>
      ))}
    </nav>
  );
}
