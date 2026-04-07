import React, { useEffect, useRef, useState, useCallback } from "react";

interface AnimatedCounterProps {
  /** Target value to count to (e.g., 275, 0.55, -0.81, 3) */
  target: number;
  /** Prefix like "+" or "−" */
  prefix?: string;
  /** Number of decimal places */
  decimals?: number;
  /** Duration of the animation in ms */
  duration?: number;
}

/**
 * Counts from 0 to `target` using requestAnimationFrame when visible.
 * Uses an easeOutCubic curve for a satisfying deceleration effect.
 */
export default function AnimatedCounter({
  target,
  prefix = "",
  decimals = 0,
  duration = 2000,
}: AnimatedCounterProps): React.JSX.Element {
  const [display, setDisplay] = useState(`${prefix}${(0).toFixed(decimals)}`);
  const [hasAnimated, setHasAnimated] = useState(false);
  const ref = useRef<HTMLSpanElement>(null);

  const animate = useCallback(() => {
    const startTime = performance.now();
    const absTarget = Math.abs(target);

    function tick(now: number) {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      // easeOutCubic
      const eased = 1 - Math.pow(1 - progress, 3);
      const current = eased * absTarget;
      setDisplay(`${prefix}${current.toFixed(decimals)}`);

      if (progress < 1) {
        requestAnimationFrame(tick);
      } else {
        setDisplay(`${prefix}${absTarget.toFixed(decimals)}`);
      }
    }

    requestAnimationFrame(tick);
  }, [target, prefix, decimals, duration]);

  useEffect(() => {
    const el = ref.current;
    if (!el || hasAnimated) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setHasAnimated(true);
          animate();
          observer.disconnect();
        }
      },
      { threshold: 0.3 },
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, [hasAnimated, animate]);

  return <span ref={ref}>{display}</span>;
}
