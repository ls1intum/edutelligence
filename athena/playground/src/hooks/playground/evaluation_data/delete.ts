import base_url from "@/helpers/base_url";
import { useMutation, UseMutationOptions } from "@tanstack/react-query";

export default function useDeleteEvaluationData(
  options: Omit<
    UseMutationOptions<{ success: boolean }, Error, { dataMode: string }>, 
    "mutationFn"
  > = {}
) {
  return useMutation({
    mutationFn: async ({ dataMode }) => {
      const response = await fetch(`${base_url}/api/data/${dataMode}/data/delete`, {
        method: "DELETE",
      });
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.error || "Failed to delete data");
      }
      return response.json();
    },
    ...options,
  });
}
