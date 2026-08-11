import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { LlmModel, LlmModelsResponse } from "@/lib/types";

/** GET /agents/models — the catalog llm_service.MODEL_CATALOG exposes, plus which
 * providers currently have an API key configured. Shared source for any model
 * picker (agent sandbox, prospect sandbox).
 */
export function useLlmModels() {
  const [models, setModels] = useState<LlmModel[]>([]);
  const [defaultModel, setDefaultModel] = useState("");

  useEffect(() => {
    api
      .get<LlmModelsResponse>("/agents/models")
      .then((res) => {
        setModels(res.data.models);
        setDefaultModel(res.data.default);
      })
      .catch(() => setModels([]));
  }, []);

  return { models, defaultModel };
}
