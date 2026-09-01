import { useCallback, useEffect, useState } from "react";

import { api, getApiErrorMessage } from "@/lib/api";
import { PlatformPhoneNumber } from "@/lib/types";

interface PhoneNumbersResponse {
  platform: string;
  numbers: PlatformPhoneNumber[];
}

/**
 * The voice platform account's phone numbers, fetched live on every load.
 *
 * Same shape and same reasoning as usePlatformAgents: `error` is surfaced rather than
 * collapsed into an empty list, because "this account owns no numbers" and "the API key
 * is dead" look identical as an empty array and have completely different fixes. The
 * settings page previously showed two invented numbers here, which is the failure this
 * replaces.
 */
export function usePhoneNumbers() {
  const [numbers, setNumbers] = useState<PlatformPhoneNumber[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    setLoading(true);
    setError(null);
    api
      .get<PhoneNumbersResponse>("/phone-numbers")
      .then((res) => setNumbers(res.data.numbers))
      .catch((err) => {
        setNumbers([]);
        setError(getApiErrorMessage(err, "Could not reach the voice platform."));
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(reload, [reload]);

  return { numbers, loading, error, reload };
}
