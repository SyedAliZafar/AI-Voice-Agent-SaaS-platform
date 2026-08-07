"use client";

import { TextareaHTMLAttributes } from "react";

import { cx } from "@/lib/cx";

import { inputBase } from "./inputBase";

export function TextArea(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cx(inputBase, "resize-y", props.className)} />;
}
