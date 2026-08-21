import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { Agent, AgentTemplate, AgentTemplatesResponse } from "@/lib/types";

export function useAgentTemplates() {
  const [templates, setTemplates] = useState<AgentTemplate[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .get<AgentTemplatesResponse>("/agents/templates")
      .then((res) => setTemplates(res.data.templates))
      .catch(() => setTemplates([]))
      .finally(() => setLoading(false));
  }, []);

  return { templates, loading };
}

/** Creates an Agent from one template leaf. Composition (reading industries.py etc.)
 * happens server-side — this just carries the (style, service, industry) key triple,
 * so the template content stays in exactly one place (scripts/agent_templates). */
export async function createAgentFromTemplate(
  template: AgentTemplate,
  name?: string,
): Promise<Agent> {
  const res = await api.post<Agent>("/agents/from-template", {
    style: template.style,
    service: template.service,
    industry: template.industry,
    name: name || undefined,
  });
  return res.data;
}
