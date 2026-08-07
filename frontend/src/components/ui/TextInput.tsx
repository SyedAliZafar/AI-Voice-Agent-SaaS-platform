"use client";

import { InputHTMLAttributes } from "react";

import { cx } from "@/lib/cx";

import { inputBase } from "./inputBase";

export function TextInput(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cx(inputBase, props.className)} />;
}
