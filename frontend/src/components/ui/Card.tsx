import { ReactNode } from "react";

import { cx } from "@/lib/cx";

export function Card({
  className,
  children,
}: {
  className?: string;
  children: ReactNode;
}) {
  return <div className={cx("card", className)}>{children}</div>;
}
