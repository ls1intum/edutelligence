import type ModuleResponse from "@/model/module_response";

import { useQuery } from "@tanstack/react-query";
import type { QueryKey, UseQueryOptions } from "@tanstack/react-query";
import { AthenaError, useAthenaFetcher } from "@/hooks/athena_fetcher";
import { useModule } from "@/hooks/module_context";

/**
 * Fetches the config schema from an Athena module.
 *
 * @example
 * const { data, isLoading, error } = useConfigSchema();
 * 
 * @param options The TanStack Query options.
 */
export default function useConfigSchema(
  options: Omit<UseQueryOptions<ModuleResponse, AthenaError>, "queryFn" | "queryKey"> & {
    queryKey?: QueryKey;
  } = {}
) {
  const { module } = useModule();
  const athenaFetcher = useAthenaFetcher();
  return useQuery<ModuleResponse, AthenaError>({
    queryKey: ["config_schema", module?.name],
    queryFn: async () => {
      return await athenaFetcher("/config_schema");
    },
    ...options,
  });
}
