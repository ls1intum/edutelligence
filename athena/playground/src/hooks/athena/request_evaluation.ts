import type { Exercise } from "@/model/exercise";
import type { Submission } from "@/model/submission";
import type ModuleResponse from "@/model/module_response";

import { UseMutationOptions, useMutation } from "@tanstack/react-query";
import { AthenaError, useAthenaFetcher } from "@/hooks/athena_fetcher";
import { Feedback } from "@/model/feedback";
import { useModule } from "@/hooks/module_context";
import useHealth from "@/hooks/health";

/**
 * Requests an evaluation for an exercise and a submission given the true and predicted feedbacks from healthy Athena modules.
 *
 * @param options The react-query options.
 * @param onlyUseContextModule - If true, only the context module is used for the evaluation. Otherwise, all healthy modules are used.
 *
 * @example
 * const { data, isLoading, error, mutate } = useRequestEvaluation();
 * mutate({ exercise, submission, trueFeedbacks, predictedFeedbacks });
 */
export default function useRequestEvaluation(
  options: Omit<
    UseMutationOptions<
      ModuleResponse[] | undefined,
      AthenaError,
      {
        exercise: Exercise;
        submission: Submission;
        trueFeedbacks: Feedback[];
        predictedFeedbacks: Feedback[];
      }
    >,
    "mutationFn"
  > = {},
  onlyUseContextModule = false
) {
  const athenaFetcher = useAthenaFetcher();
  const { module: contextModule } = useModule();
  const { data: health } = useHealth();

  return useMutation({
    mutationFn: async ({
      exercise,
      submission,
      trueFeedbacks,
      predictedFeedbacks,
    }) => {
      const modules = onlyUseContextModule
        ? [contextModule]
        : Object.values(health?.modules ?? {}).filter(
            (module) => module.healthy && module.type === contextModule.type && module.supportsEvaluation
          );

      const results = await Promise.allSettled(
        modules.map((module) =>
          athenaFetcher(
            "/evaluation",
            {
              exercise,
              submission,
              true_feedbacks: trueFeedbacks,
              predicted_feedbacks: predictedFeedbacks,
            },
            { module: module, moduleConfig: undefined }
          )
        )
      );

      return results.flatMap((result) => {
        if (result.status === "fulfilled") {
          return [result.value];
        } else {
          return [];
        }
      });
    },
    ...options,
  });
}
