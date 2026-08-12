import { sortLabels, UNSPECIFIED } from "@/lib/prospectGrouping";

export { sortLabels, UNSPECIFIED };

/** Agent names created by scripts/build_agent_matrix.py follow
 * "{Industry} Outbound — {Service} — {Style} v1". Older hand-created agents (e.g.
 * "HVAC/Solar Outbound — Test v1") only have the industry segment, so those fall back to
 * UNSPECIFIED for service/style rather than being hidden — this is presentational
 * parsing only, no backend field, so it never drops an agent it can't fully parse.
 */
export interface ParsedAgentName {
  industry: string;
  service: string;
  style: string;
}

const OUTBOUND_SUFFIX = /\s+outbound$/i;
const VERSION_SUFFIX = /\s+v\d+$/i;

export function parseAgentName(name: string): ParsedAgentName {
  const parts = name.split(" — ").map((p) => p.trim());

  if (parts.length < 2) {
    return { industry: UNSPECIFIED, service: UNSPECIFIED, style: UNSPECIFIED };
  }

  const industry = parts[0].replace(OUTBOUND_SUFFIX, "").trim() || UNSPECIFIED;

  if (parts.length >= 3) {
    const service = parts[1] || UNSPECIFIED;
    const style = parts[2].replace(VERSION_SUFFIX, "").trim() || UNSPECIFIED;
    return { industry, service, style };
  }

  const service = parts[1].replace(VERSION_SUFFIX, "").trim() || UNSPECIFIED;
  return { industry, service, style: UNSPECIFIED };
}
