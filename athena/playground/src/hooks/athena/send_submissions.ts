import type ModuleResponse from "@/model/module_response";
import type { Exercise } from "@/model/exercise";
import type { Submission } from "@/model/submission";

import { UseMutationOptions, useMutation } from "@tanstack/react-query";
import { AthenaError, useAthenaFetcher } from "@/hooks/athena_fetcher";

/**
 * Sends submissions for an exercise to an Athena module.
 *
 * @example
 * const { data, isLoading, error, mutate } = useSendSubmissions();
 * mutate({ exercise, submissions });
 * 
 * @param options The react-query options.
 */
export default function useSendSubmissions(
  options: Omit<
    UseMutationOptions<ModuleResponse | undefined, AthenaError, { exercise: Exercise; submissions: Submission[] }>,
    "mutationFn"
  > = {}
) {
  const athenaFetcher = useAthenaFetcher();
  return useMutation({
    mutationFn: async ({ exercise, submissions }) => {
      return await athenaFetcher("/submissions", { exercise, submissions });
    },
    ...options,
  });
}
