import base_url from "@/helpers/base_url";
import { useMutation, UseMutationOptions } from "@tanstack/react-query";

export default function useExportEvaluationData(
  options: Omit<
    UseMutationOptions<Blob, Error, { dataMode: string }>, 
    "mutationFn"
  > = {}
) {
  return useMutation({
    mutationFn: async ({ dataMode }) => {
      const response = await fetch(`${base_url}/api/data/${dataMode}/data/export`);
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || "Failed to export data");
      }
      return response.blob();
    },
    ...options,
  });
}
