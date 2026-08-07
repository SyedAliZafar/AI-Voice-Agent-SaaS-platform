export function cx(...parts: (string | false | undefined | null)[]) {
  return parts.filter(Boolean).join(" ");
}
