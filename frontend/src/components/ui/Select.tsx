"use client";

import { SelectHTMLAttributes } from "react";

import { cx } from "@/lib/cx";

import { inputBase } from "./inputBase";

export function Select(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cx(inputBase, "bg-white", props.className)} />;
}
