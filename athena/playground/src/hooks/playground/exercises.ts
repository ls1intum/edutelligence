import type { Exercise } from "@/model/exercise";
import type { DataMode } from "@/model/data_mode";

import { UseQueryOptions, useQuery } from "react-query";
import baseUrl from "@/helpers/base_url";
import { useBaseInfo } from "@/hooks/base_info_context";

export function fetchExercises(dataMode: DataMode) {
  return fetch(`${baseUrl}/api/data/${dataMode}/exercises`).then(
    (res) => res.json() as Promise<Exercise[]>
  );
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
  options: Omit<UseQueryOptions<Exercise[], Error, Exercise[]>, 'queryFn'> = {}
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