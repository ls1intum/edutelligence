import type { Exercise } from "@/model/exercise";
import type { Submission } from "@/model/submission";
import type ModuleResponse from "@/model/module_response";

import { UseMutationOptions, useMutation } from "@tanstack/react-query";
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
    UseMutationOptions<ModuleResponse | undefined, AthenaError, { exercise: Exercise; submission: Submission, is_graded: boolean }>,
    "mutationFn"
  > = {}
) {
  const athenaFetcher = useAthenaFetcher();
  return useMutation({
    mutationFn: async ({ exercise, submission, is_graded }) => {
      let response = await athenaFetcher("/feedback_suggestions", { exercise, submission, isGraded: is_graded });
      if (response?.data) {
        response.data = response.data.map((feedback: Feedback, index: number) => {
          // Change variable names from camel case to snake case (change this in the future, index_start -> indexStart, index_end -> indexEnd)
          feedback = Object.fromEntries(
            Object.entries(feedback).map(([key, value]) => [key.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`), value])
          ) as Feedback;

          feedback.id = Number(`${Date.now()}${String(index).padStart(3, "0")}`); // Good enough for the playground
          feedback.type = exercise.type;
          feedback.isSuggestion = true;
          return feedback;
        });
      }
      return response;
    },
    ...options,
  });
}
