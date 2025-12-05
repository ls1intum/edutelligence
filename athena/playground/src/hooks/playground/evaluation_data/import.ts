import base_url from "@/helpers/base_url";
import { useMutation, UseMutationOptions } from "@tanstack/react-query";

/**
 * Hook to import evaluation data.
 *
 * @example
 * const { data, isLoading, error, mutate } = useImportEvaluationData();
 * const formData = new FormData();
 * formData.append("file", file);
 * mutate({ dataMode: "evaluation", formData });
 * 
 * @param options The react-query options.
 */
export default function useImportEvaluationData(
  options: Omit<
    UseMutationOptions<{ success: boolean }, Error, { dataMode: string; formData: FormData }>, 
    "mutationFn"
  > = {}
) {
  return useMutation({
    mutationFn: async ({ dataMode, formData }) => {
      const response = await fetch(`${base_url}/api/data/${dataMode}/data/import`, {
        method: "POST",
        body: formData,
      });
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || "Failed to import data");
      }
      return response.json();
    },
    ...options,
  });
}
