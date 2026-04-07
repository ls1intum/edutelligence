import { useEffect, useRef, useState } from "react";

/**
 * Lightweight scroll-triggered fade-in using IntersectionObserver.
 * Returns a ref to attach to the element and a boolean `visible` flag.
 * Once visible, stays visible (no re-hiding on scroll-out).
 */
export function useFadeIn(
  threshold = 0.15,
): [React.RefObject<HTMLElement | null>, boolean] {
  const ref = useRef<HTMLElement | null>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { threshold },
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, [threshold]);

  return [ref, visible];
}
