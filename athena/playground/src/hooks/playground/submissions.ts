import type { Exercise } from "@/model/exercise";
import type { Submission } from "@/model/submission";

import { UseQueryOptions, useQuery } from "react-query";
import baseUrl from "@/helpers/base_url";
import { useBaseInfo } from "@/hooks/base_info_context";

/**
 * Fetches the submissions for an exercise of the playground.
 * 
 * @example
 * const { data, isLoading, error } = useSubmissions(exercise);
 * 
 * @param exercise The exercise to fetch the submissions for.
 * @param options The react-query options.
 */
export default function useSubmissions(
  exercise?: Exercise,
  options: Omit<UseQueryOptions<Submission[], Error, Submission[]>, 'queryFn'> = {}
) {
  const { mode } = useBaseInfo();

  return useQuery<Submission[], Error, Submission[], any>({
    queryKey: ["submissions", mode, exercise?.id],
    queryFn: async () => {
      if (exercise === undefined) {
        return undefined;
      }
      const response = await fetch(`${baseUrl}/api/mode/${mode}/exercise/${exercise.id}/submissions`);
      return await response.json() as Submission[];
    },
    ...options
  });
}