import type { Exercise } from "@/model/exercise";
import type { DataMode } from "@/model/data_mode";

import { UseQueryOptions, useQuery } from "@tanstack/react-query";
import baseUrl from "@/helpers/base_url";
import { useBaseInfo } from "@/hooks/base_info_context";

export async function fetchExercises(dataMode: DataMode) {
  const response = await fetch(`${baseUrl}/api/data/${dataMode}/exercises`);
  return await response.json() as Promise<Exercise[]>;
}

/**
 * Fetches the exercises of the playground.
 * 
 * @example
 * const { data, isLoading, error } = useExercises();
 * 
 * @param options The react-query options.
 */
export default function useExercises(
  options: Omit<UseQueryOptions<Exercise[], Error, Exercise[]>, 'queryFn'> & { eager?: boolean } = {},
) {
  const { dataMode } = useBaseInfo();

  return useQuery({
    queryKey: ["exercises", dataMode],
    queryFn: async () => {
      return await fetchExercises(dataMode);
    },
    ...options
  });
}
