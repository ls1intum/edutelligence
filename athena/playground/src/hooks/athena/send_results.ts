import { AthenaError, useAthenaFetcher } from "@/hooks/athena_fetcher";
import type ModuleResponse from "@/model/module_response";
import { UseMutationOptions, useMutation } from "react-query";
import { useModule } from "@/hooks/module_context";
import useHealth from "@/hooks/health";
import { Exercise } from "@/model/exercise";

/**
 * Hook to send results data to the backend.
 *
 * @param options React Query mutation options.
 *
 * @example
 * const { mutate, isLoading } = useSendResults();
 * mutate(statisticsData);
 */
export function useSendResults(
  options: Omit<
    UseMutationOptions<
      ModuleResponse[] | undefined,
      AthenaError,
      { exercise:Exercise; results: any }
    >,
    "mutationFn"
  > = {},
  onlyUseContextModule = false
) {
  const athenaFetcher = useAthenaFetcher();
  const { module: contextModule } = useModule();
  const { data: health } = useHealth();

  return useMutation({
    mutationFn: async ( data ) => {
      // Get the list of modules to evaluate
      const modules = onlyUseContextModule
        ? [contextModule]
        : Object.values(health?.modules ?? {}).filter(
            (module) =>
              module.healthy &&
              module.type === contextModule.type &&
              module.supportsEvaluation
          );

      // Map over each module and send the data
      const results = await Promise.allSettled(
        modules.map((module) =>
          athenaFetcher(
            "/generate_statistics", // The route to call
            { data }, // The payload
            { module, moduleConfig: undefined }
          )
        )
      );

      // Filter and process the results
      return results.flatMap((result) => {
        if (result.status === "fulfilled") {
          return [result.value];
        } else {
          console.error("Error fetching statistics:", result.reason);
          return [];
        }
      });
    },
    ...options,
  });
}
