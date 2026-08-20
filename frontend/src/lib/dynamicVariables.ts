import { Prospect } from "@/lib/types";

/**
 * Suggested values for a platform agent's {{placeholders}} (ADR-012).
 *
 * The names are whatever the prompt's author typed in Retell's dashboard, so nothing can
 * be guaranteed — this maps the handful of conventional ones onto data we already hold
 * and leaves the rest blank for the operator. Every suggestion lands in an editable
 * field, never straight into the request: a wrong guess spoken to a real prospect is
 * worse than an empty box the operator has to fill.
 *
 * Matching is case-insensitive and ignores separators, so company_name / companyName /
 * CompanyName are one key. Aliases exist because two prompts rarely agree on a name.
 */
const ALIASES: Record<string, string[]> = {
  companyname: ["company", "businessname", "business", "prospectname", "accountname"],
  contactname: ["contact", "name", "firstname", "ownername", "customername"],
  phonenumber: ["usernumber", "phone", "tonumber", "callernumber", "contactnumber"],
  city: ["town", "location"],
  industry: ["niche", "category", "vertical"],
};

function normalize(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]/g, "");
}

/** Resolve a declared variable name to one of our canonical keys, or null. */
function canonicalKey(name: string): string | null {
  const key = normalize(name);
  if (key in ALIASES) return key;
  for (const [canonical, aliases] of Object.entries(ALIASES)) {
    if (aliases.includes(key)) return canonical;
  }
  return null;
}

/**
 * Fill what we can for a prospect call. `current_time` is included because Retell's own
 * dashboard lists it as operator-supplied rather than auto-injecting it, and an agent
 * that asks the time should not be told "{{current_time}}".
 */
export function suggestProspectVariables(
  declared: string[],
  prospect: Prospect,
): Record<string, string> {
  const values: Record<string, string> = {
    companyname: prospect.name || "",
    contactname: "", // research holds no named contact today — operator's to supply
    phonenumber: prospect.phone || "",
    city: prospect.city || "",
    industry: prospect.research?.industry || prospect.category || "",
  };

  const out: Record<string, string> = {};
  for (const name of declared) {
    if (normalize(name) === "currenttime") {
      out[name] = new Date().toLocaleString();
      continue;
    }
    const key = canonicalKey(name);
    out[name] = key ? values[key] || "" : "";
  }
  return out;
}
