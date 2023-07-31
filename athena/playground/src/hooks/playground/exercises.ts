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
  const { dataMode } = useBaseInfo();

  return useQuery({
    queryKey: ["exercises", dataMode],
    queryFn: async () => {
      const response = await fetch(`${baseUrl}/api/data/${dataMode}/exercises`);
      return await response.json() as Exercise[];
    },
    ...options
  });
}