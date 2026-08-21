import { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement>;

function Base({ children, ...props }: IconProps & { children: React.ReactNode }) {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {children}
    </svg>
  );
}

export function DashboardIcon(props: IconProps) {
  return (
    <Base {...props}>
      <rect x="3" y="3" width="7" height="9" rx="1.5" />
      <rect x="14" y="3" width="7" height="5" rx="1.5" />
      <rect x="14" y="12" width="7" height="9" rx="1.5" />
      <rect x="3" y="16" width="7" height="5" rx="1.5" />
    </Base>
  );
}

export function AgentsIcon(props: IconProps) {
  return (
    <Base {...props}>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 21c0-3.5 3.6-6 8-6s8 2.5 8 6" />
    </Base>
  );
}

export function CallsIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M4.5 4h3l1.5 4.5-2 1.5a12 12 0 0 0 5 5l1.5-2 4.5 1.5v3a2 2 0 0 1-2.2 2A16 16 0 0 1 2.5 6.2 2 2 0 0 1 4.5 4Z" />
    </Base>
  );
}

export function LiveIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M3 12h2l2-5 4 14 3-9 2 3h5" />
    </Base>
  );
}

export function SettingsIcon(props: IconProps) {
  return (
    <Base {...props}>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1" />
    </Base>
  );
}

export function PlusIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M12 5v14M5 12h14" />
    </Base>
  );
}

export function SearchIcon(props: IconProps) {
  return (
    <Base {...props}>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </Base>
  );
}

export function ChevronRightIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="m9 6 6 6-6 6" />
    </Base>
  );
}

export function ArrowLeftIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M19 12H5M12 19l-7-7 7-7" />
    </Base>
  );
}

export function ClockIcon(props: IconProps) {
  return (
    <Base {...props}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" />
    </Base>
  );
}

export function PhoneIcon(props: IconProps) {
  return <CallsIcon {...props} />;
}

export function CloseIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M18 6 6 18M6 6l12 12" />
    </Base>
  );
}

export function CheckIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M20 6 9 17l-5-5" />
    </Base>
  );
}

export function SparkleIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M12 3v6M12 15v6M3 12h6M15 12h6" />
      <path d="M12 9a3 3 0 0 0 3 3 3 3 0 0 0-3 3 3 3 0 0 0-3-3 3 3 0 0 0 3-3Z" />
    </Base>
  );
}

export function PlugIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M9 2v6M15 2v6M7 8h10v3a5 5 0 0 1-10 0V8ZM12 16v6" />
    </Base>
  );
}

export function CreditCardIcon(props: IconProps) {
  return (
    <Base {...props}>
      <rect x="2" y="5" width="20" height="14" rx="2" />
      <path d="M2 10h20" />
    </Base>
  );
}

export function HashIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M4 9h16M4 15h16M10 3 8 21M16 3l-2 18" />
    </Base>
  );
}

export function TargetIcon(props: IconProps) {
  return (
    <Base {...props}>
      <circle cx="12" cy="12" r="8" />
      <circle cx="12" cy="12" r="4" />
      <circle cx="12" cy="12" r="0.5" fill="currentColor" />
    </Base>
  );
}

export function RefreshIcon(props: IconProps) {
  return (
    <Base {...props}>
      <path d="M3 12a9 9 0 0 1 15.5-6.3L21 8" />
      <path d="M21 3v5h-5" />
      <path d="M21 12a9 9 0 0 1-15.5 6.3L3 16" />
      <path d="M3 21v-5h5" />
    </Base>
  );
}

export function MicIcon(props: IconProps) {
  return (
    <Base {...props}>
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M5 10a7 7 0 0 0 14 0M12 19v3" />
    </Base>
  );
}

/** Brand mark — rounded square with a stylized sound wave. */
export function BrandMark(props: IconProps) {
  return (
    <svg
      width="32"
      height="32"
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
      {...props}
    >
      <rect width="32" height="32" rx="9" fill="#4f46e5" />
      <g stroke="#fff" strokeWidth="2" strokeLinecap="round">
        <path d="M9 13v6" />
        <path d="M13 9v14" />
        <path d="M17 11v10" />
        <path d="M21 14v4" />
      </g>
    </svg>
  );
}
