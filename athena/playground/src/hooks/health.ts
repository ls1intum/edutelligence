import type { HealthResponse } from "@/model/health_response";

import { UseQueryOptions, useQuery } from "@tanstack/react-query";
import baseUrl from "@/helpers/base_url";
import { useBaseInfo } from "@/hooks/base_info_context";

/**
 * Fetches the health of Athena.
 *
 * @example
 * const { data, isLoading, error } = useHealth();
 *
 * @param options The react-query options.
 */
export default function useHealth(
  options: Omit<UseQueryOptions<HealthResponse, Error, HealthResponse>, "queryFn"> = {}
) {
  const { athenaUrl } = useBaseInfo();
  return useQuery<HealthResponse, Error, HealthResponse, any>({
    queryKey: ["health", athenaUrl],
    queryFn: async () =>
      fetch(`${baseUrl}/api/health?url=${encodeURIComponent(athenaUrl)}`).then(
        (res) => res.json() as Promise<HealthResponse>
      ),
    ...options,
  });
}
