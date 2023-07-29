import type { Exercise } from "@/model/exercise";
import type { Submission } from "@/model/submission";
import type ModuleResponse from "@/model/module_response";

import { UseMutationOptions, useMutation } from "react-query";
import { AthenaError, useAthenaFetcher } from "@/hooks/athena_fetcher";
import { Feedback } from "@/model/feedback";

/**
 * Requests feedback suggestions for an exercise and a submission from an Athena module.
 *
 * @example
 * const { data, isLoading, error, mutate } = useRequestFeedbackSuggestions();
 * mutate({ exercise, submission });
 * 
 * @param options The react-query options.
 */
export default function useRequestFeedbackSuggestions(
  options: Omit<
    UseMutationOptions<ModuleResponse | undefined, AthenaError, { exercise: Exercise; submission: Submission }>, 
    "mutationFn"
  > = {}
) {
  const athenaFetcher = useAthenaFetcher();
  return useMutation({
    mutationFn: async ({ exercise, submission }) => {
      let response = await athenaFetcher("/feedback_suggestions", { exercise, submission });
      if (response?.data) {
        // Add is_suggestion flag to feedbacks
        response.data.feedbacks = response.data.map((feedback: Feedback) => {
          feedback.is_suggestion = true;
          return feedback;
        });
      }
      return response;
    },
    ...options,
  });
}
