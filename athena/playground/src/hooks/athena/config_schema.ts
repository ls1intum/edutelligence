import type ModuleResponse from "@/model/module_response";

import { UseQueryOptions, useQuery } from "@tanstack/react-query";
import { AthenaError, useAthenaFetcher } from "@/hooks/athena_fetcher";
import { useModule } from "@/hooks/module_context";

/**
 * Fetches the config schema from an Athena module.
 *
 * @example
 * const { data, isLoading, error } = useConfigSchema();
 * 
 * @param options The react-query options.
 */
export default function useConfigSchema(options: Omit<UseQueryOptions<ModuleResponse, Error, ModuleResponse>, 'queryFn'> = {}) {
  const { module } = useModule();
  const athenaFetcher = useAthenaFetcher();
  return useQuery<ModuleResponse, AthenaError, ModuleResponse, any>({
    queryKey: ["config_schema", module?.name],
    queryFn: async () => {
      return await athenaFetcher("/config_schema");
    },
    ...options,
  });
}
