import { useEffect, useState, type ReactNode } from "react";

/**
 * Restrained, accessible motion primitives, done with CSS transitions only.
 *
 * Content mounts in a near-visible state (class `fade-enter`) and the
 * `is-in` class is added on the next frame, so the browser transitions
 * opacity and a small translate. Under prefers-reduced-motion the CSS renders
 * `.fade-enter` in its final state with no transition, so data is never
 * delayed for animation. Staggering is a per-child transition-delay in CSS.
 */
function useEntered(key?: string): boolean {
  const [entered, setEntered] = useState(false);
  useEffect(() => {
    setEntered(false);
    let raf2 = 0;
    // Two frames: the first commits the initial state, the second flips it.
    const raf1 = requestAnimationFrame(() => {
      raf2 = requestAnimationFrame(() => setEntered(true));
    });
    return () => {
      cancelAnimationFrame(raf1);
      cancelAnimationFrame(raf2);
    };
  }, [key]);
  return entered;
}

function cx(...parts: Array<string | false | undefined>): string {
  return parts.filter(Boolean).join(" ");
}

export function FadeIn({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  const entered = useEntered();
  return (
    <div className={cx("fade-enter", entered && "is-in", className)}>
      {children}
    </div>
  );
}

export function Stagger({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <div className={cx("stagger", className)}>{children}</div>;
}

export function StaggerItem({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <FadeIn className={className}>{children}</FadeIn>;
}

/** Keyed wrapper for switching main views; fades in on navigation. */
export function ViewFade({
  viewKey,
  children,
}: {
  viewKey: string;
  children: ReactNode;
}) {
  const entered = useEntered(viewKey);
  return (
    <div className={cx("fade-enter", "view-fade", entered && "is-in")}>
      {children}
    </div>
  );
}
