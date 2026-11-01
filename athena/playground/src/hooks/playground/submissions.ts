import type { Exercise } from "@/model/exercise";
import type { Submission } from "@/model/submission";
import type { DataMode } from "@/model/data_mode";

import { useQuery } from "@tanstack/react-query";
import type { UseQueryOptions } from "@tanstack/react-query";
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
 * @param options The TanStack Query options.
 */
export default function useSubmissions(
  exercise?: Exercise,
  options: Omit<UseQueryOptions<Submission[]>, "queryFn" | "queryKey"> = {}
) {
  const { dataMode } = useBaseInfo();

  return useQuery<Submission[], Error>({
    queryKey: ["submissions", dataMode, exercise?.id],
    queryFn: async () => {
      if (exercise === undefined) {
        throw new Error("An exercise must be selected before loading submissions");
      }
      return await fetchSubmissions(exercise, dataMode);
    },
    ...options,
    enabled: exercise !== undefined && (options.enabled ?? true),
  });
}
