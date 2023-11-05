import type { Exercise } from "@/model/exercise";
import type { Submission } from "@/model/submission";
import type ModuleResponse from "@/model/module_response";

import { UseMutationOptions, useMutation } from "react-query";
import { AthenaError, useAthenaFetcher } from "@/hooks/athena_fetcher";
import { Feedback } from "@/model/feedback";

/**
 * Requests an evaluation for an exercise and a submission given the true and predicted feedbacks from an Athena module.
 *
 * @example
 * const { data, isLoading, error, mutate } = useRequestEvaluation();
 * mutate({ exercise, submission, trueFeedbacks, predictedFeedbacks });
 * 
 * @param options The react-query options.
 */
export default function useRequestEvaluation(
  options: Omit<
    UseMutationOptions<ModuleResponse | undefined, AthenaError, { exercise: Exercise; submission: Submission, trueFeedbacks: Feedback[], predictedFeedbacks: Feedback[] }>,
    "mutationFn"
  > = {}
) {
  const athenaFetcher = useAthenaFetcher();
  return useMutation({
    mutationFn: async ({ exercise, submission, trueFeedbacks, predictedFeedbacks }) => {
      return await athenaFetcher("/evaluation", { exercise, submission, true_feedbacks: trueFeedbacks, predicted_feedbacks: predictedFeedbacks });
    },
    ...options,
  });
}
