import type ModuleResponse from "@/model/module_response";
import type { Feedback } from "@/model/feedback";
import type { Exercise } from "@/model/exercise";
import type { Submission } from "@/model/submission";

import { UseMutationOptions, useMutation } from "react-query";
import { AthenaError, useAthenaFetcher } from "@/hooks/athena_fetcher";

/**
 * Sends feedback for an exercise and a submission to an Athena module.
 *
 * @example
 * const { data, isLoading, error, mutate } = useSendFeedback();
 * mutate({ exercise, submission, feedback });
 *
 * @param options The react-query options.
 */
export function useSendFeedback(
  options: Omit<
    UseMutationOptions<ModuleResponse | undefined, AthenaError, { exercise: Exercise; submission: Submission; feedback: Feedback; }>,
    "mutationFn"
  > = {}
) {
  const athenaFetcher = useAthenaFetcher();
  return useMutation({
    mutationFn: async ({ exercise, submission, feedback }) => {
      return await athenaFetcher("/feedback", { exercise, submission, feedback });
    },
    ...options,
  });
}


/**
 * Sends feedbacks for an exercise and a submission to an Athena module.
 *
 * @example
 * const { data, isLoading, error, mutate } = useSendFeedbacks();
 * mutate([{ exercise, submission, feedback }]);
 *
 * @param options The react-query options.
 */
export function useSendFeedbacks(
  options: Omit<
    UseMutationOptions<(ModuleResponse | undefined)[], AthenaError, { exercise: Exercise; submission: Submission; feedback: Feedback; }[]>,
    "mutationFn"
  > = {}
) {
  const athenaFetcher = useAthenaFetcher();
  return useMutation({
    mutationFn: async (items) => {
      return await Promise.all(
        items.map(async ({ exercise, submission, feedback }) =>
          athenaFetcher("/feedback", { exercise, submission, feedback })
        )
      );
    },
    ...options,
  });
}
