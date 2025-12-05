import type { Feedback } from "@/model/feedback";
import type { Submission } from "@/model/submission";
import type { Exercise } from "@/model/exercise";
import type { DataMode } from "@/model/data_mode";

import { UseQueryOptions, useQuery } from "@tanstack/react-query";
import baseUrl from "@/helpers/base_url";
import { useBaseInfo } from "@/hooks/base_info_context";

export async function fetchFeedbacks(
  exercise: Exercise | undefined,
  submission: Submission | undefined,
  dataMode: DataMode
) {
  const response = await fetch(
    `${baseUrl}/api/data/${dataMode}/${exercise ? `exercise/${exercise.id}/` : ""}feedbacks`
  );

  let feedbacks = await response.json() as Feedback[];
  for (const feedback of feedbacks) {
    if (feedback.structured_grading_instruction_id) {
      feedback.structured_grading_instruction = exercise?.grading_criteria?.flatMap((criteria) => criteria.structured_grading_instructions).find((instruction) => instruction.id === feedback.structured_grading_instruction_id);
    }
  }

  if (submission) {
    return feedbacks.filter((feedback) => feedback.submission_id === submission.id);
  }
  return feedbacks;
}

/**
 * Fetches the feedbacks (for an exercise) of the playground.
 * 
 * @example
 * const { data, isLoading, error } = useFeedbacks(exercise);
 * 
 * @param exercise The exercise to fetch the feedbacks for.
 * @param submission The submission to fetch the feedbacks for.
 * @param options The react-query options.
 */
export default function useFeedbacks(
  exercise?: Exercise,
  submission?: Submission,
  options: Omit<UseQueryOptions<Feedback[], Error, Feedback[]>, 'queryFn'> = {}
) {
  const { dataMode } = useBaseInfo();

  return useQuery({
    queryKey: ["feedbacks", dataMode, exercise?.id, submission?.id],
    queryFn: async () => {
      return fetchFeedbacks(exercise, submission, dataMode);
    },
    ...options
  });
}
