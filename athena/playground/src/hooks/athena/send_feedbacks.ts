import type ModuleResponse from "@/model/module_response";
import type { Feedback } from "@/model/feedback";
import type { Exercise } from "@/model/exercise";
import type { Submission } from "@/model/submission";

import { UseMutationOptions, useMutation } from "@tanstack/react-query";
import { AthenaError, useAthenaFetcher } from "@/hooks/athena_fetcher";

/**
 * Sends feedbacks for an exercise and a submission to an Athena module.
 *
 * @example
 * const { data, isLoading, error, mutate } = useSendFeedbacks();
 * mutate({ exercise, submission, feedbacks });
 *
 * @param options The react-query options.
 */
export function useSendFeedbacks(
  options: Omit<
    UseMutationOptions<ModuleResponse | undefined, AthenaError, { exercise: Exercise; submission: Submission; feedbacks: Feedback[]; }>,
    "mutationFn"
  > = {}
) {
  const athenaFetcher = useAthenaFetcher();
  return useMutation({
    mutationFn: async ({ exercise, submission, feedbacks }) => {
      return await athenaFetcher("/feedbacks", { exercise, submission, feedbacks });
    },
    ...options,
  });
}
