import type { Exercise } from "@/model/exercise";
import type { Submission } from "@/model/submission";
import type { DataMode } from "@/model/data_mode";

import { UseQueryOptions, useQuery } from "@tanstack/react-query";
import baseUrl from "@/helpers/base_url";
import { useBaseInfo } from "@/hooks/base_info_context";

export async function fetchSubmissions(exercise: Exercise, dataMode: DataMode) {
  const response = await fetch(`${baseUrl}/api/data/${dataMode}/exercise/${exercise.id}/submissions`);
  return await response.json() as Promise<Submission[]>;
}

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
  const { dataMode } = useBaseInfo();

  return useQuery<Submission[], Error, Submission[], any>({
    queryKey: ["submissions", dataMode, exercise?.id],
    queryFn: async () => {
      if (exercise === undefined) {
        return undefined;
      }
      return await fetchSubmissions(exercise, dataMode);
    },
    ...options
  });
}
