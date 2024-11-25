import React from "react";
import { ExpertEvaluationConfig } from "@/model/expert_evaluation_config";

type EvaluationConfigSelectorProps = {
  selectedConfigId: string;
  setSelectedConfigId: (id: string) => void;
  expertEvaluationConfigs: ExpertEvaluationConfig[];
};

export default function EvaluationConfigSelector(evaluationConfigSelectorProps: EvaluationConfigSelectorProps) {
  const { selectedConfigId, setSelectedConfigId, expertEvaluationConfigs } = evaluationConfigSelectorProps;
  return (
    <section className="flex flex-col">
      <span className="text-lg font-bold mb-2">Evaluation</span>
      <select
        className="border border-gray-300 rounded-md p-2"
        value={selectedConfigId}
        onChange={(e) => setSelectedConfigId(e.target.value)}
      >
        <option value="new">New Evaluation</option>
        {expertEvaluationConfigs.map((config) => (
          <option key={config.id} value={config.id}>
            {config.name}: {config.creationDate?.toString() ?? ""}
          </option>
        ))}
      </select>
    </section>
  );
};
