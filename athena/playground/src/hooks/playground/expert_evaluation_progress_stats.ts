import baseUrl from "@/helpers/base_url";
import { ExpertEvaluationProgressStats } from "@/model/expert_evaluation_progress_stats";

export async function fetchExpertEvaluationProgressStats(
  expertEvaluationId: string
) {
  const response = await fetch(`${baseUrl}/api/data/expert_evaluation/expert_evaluation/${expertEvaluationId}/progress_stats`);

  return await response.json() as Promise<ExpertEvaluationProgressStats>;
}
