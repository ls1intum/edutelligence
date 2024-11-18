import baseUrl from "@/helpers/base_url";
import { ExpertEvaluationConfig } from "@/model/expert_evaluation_config";
import { DataMode } from "@/model/data_mode";

/** Saves a new or existing expert evaluation config to the server */
export async function saveExpertEvaluationConfig(
    dataMode: DataMode,
    config: ExpertEvaluationConfig,
    isCreate: boolean) {

    const response = await fetch(`${baseUrl}/api/data/${dataMode}/expert_evaluation/${config.id}/config`, {
        method: isCreate ? 'POST' : 'PUT',
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(config),
    });

    if (!response.ok) {
        throw new Error("Failed to save expert evaluation config");
    }
    return await response.json() as Promise<ExpertEvaluationConfig>;
}

export async function fetchExpertEvaluationConfig(
    dataMode: DataMode,
    expertEvaluationId: string
) {
    const response = await fetch(`${baseUrl}/api/data/${dataMode}/expert_evaluation/${expertEvaluationId}/config`);

    if (!response.ok) {
        throw new Error("Failed to fetch expert evaluation config");
    }

    return await response.json() as Promise<ExpertEvaluationConfig>;
}

/** Fetches the list of expert evaluation configs from the server */
export async function fetchAllExpertEvaluationConfigs(
    dataMode: DataMode
) {
    const response = await fetch(`${baseUrl}/api/data/${dataMode}/expert_evaluation/configs`);

    if (!response.ok) {
        throw new Error("Failed to fetch expert evaluation configs");
    }

    return await response.json() as Promise<ExpertEvaluationConfig[]>;
}
