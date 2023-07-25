import type { Exercise } from "@/model/exercise";

import { UseQueryOptions, useQuery } from "react-query";
import baseUrl from "@/helpers/base_url";
import { useBaseInfo } from "@/hooks/base_info_context";

/**
 * Fetches the exercises of the playground.
 * 
 * @example
 * const { data, isLoading, error } = useExercises();
 * 
 * @param options The react-query options.
 */
export default function useExercises(
  options: Omit<UseQueryOptions<Exercise[], Error, Exercise[]>, 'queryFn'> = {}
) {
  const { mode } = useBaseInfo();

  return useQuery({
    queryKey: ["exercises", mode],
    queryFn: async () => {
      const response = await fetch(`${baseUrl}/api/mode/${mode}/exercises`);
      return await response.json() as Exercise[];
    },
    ...options
  });
}