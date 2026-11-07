import type { SVGProps } from "react";

/**
 * One consistent line-icon set (24px grid, 1.75 stroke, round joins),
 * drawn as SVG rather than borrowed glyphs or emoji. Size via font-size or
 * width/height; color via currentColor.
 */

type IconProps = SVGProps<SVGSVGElement>;

function base(props: IconProps) {
  return {
    viewBox: "0 0 24 24",
    width: "1em",
    height: "1em",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.75,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
    focusable: false,
    ...props,
  };
}

export function IconLogo(props: IconProps) {
  // A retrace "re-trace" mark: a path doubling back on itself.
  return (
    <svg {...base({ strokeWidth: 2, ...props })}>
      <path d="M5 18V8a3 3 0 0 1 3-3h5a3 3 0 0 1 0 6H9" />
      <path d="M12 11l-3 3 3 3" />
    </svg>
  );
}

export function IconOverview(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M4 13a8 8 0 0 1 16 0" />
      <path d="M12 13l3.5-3.5" />
      <circle cx="12" cy="13" r="1.1" fill="currentColor" stroke="none" />
      <path d="M4 18h16" />
    </svg>
  );
}

export function IconInvestigate(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="11" cy="11" r="6" />
      <path d="M20 20l-4.3-4.3" />
    </svg>
  );
}

export function IconEvaluations(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M9 5h9M9 12h9M9 19h9" />
      <path d="M4 5l1.4 1.4L8 4" />
      <path d="M4 12l1.4 1.4L8 11" />
      <path d="M4 19l1.4 1.4L8 18" />
    </svg>
  );
}

export function IconExperiments(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M9 3v6l-4.5 7.5A2 2 0 0 0 6.2 20h11.6a2 2 0 0 0 1.7-3.5L15 9V3" />
      <path d="M8 3h8" />
      <path d="M7.5 15h9" />
    </svg>
  );
}

export function IconOperations(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M3 12h3l2.5 6 4-13 2.5 7h6" />
    </svg>
  );
}

export function IconSun(props: IconProps) {
  return (
    <svg {...base(props)}>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
    </svg>
  );
}

export function IconMoon(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M20 14.5A8 8 0 0 1 9.5 4a7 7 0 1 0 10.5 10.5Z" />
    </svg>
  );
}

export function IconMonitor(props: IconProps) {
  return (
    <svg {...base(props)}>
      <rect x="3" y="4" width="18" height="12" rx="2" />
      <path d="M8 20h8M12 16v4" />
    </svg>
  );
}

export function IconMenu(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M4 6h16M4 12h16M4 18h16" />
    </svg>
  );
}

export function IconArrowRight(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  );
}

export function IconCheck(props: IconProps) {
  return (
    <svg {...base(props)}>
      <path d="M5 12.5l4.5 4.5L19 7" />
    </svg>
  );
}
