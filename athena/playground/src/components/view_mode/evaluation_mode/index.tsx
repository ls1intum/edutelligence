import type { Experiment } from "./define_experiment";
import type { ModuleConfiguration } from "./configure_modules";

import { useState } from "react";

import DefineExperiment from "./define_experiment";
import ConfigureModules from "./configure_modules";
import ConductExperiment from "./conduct_experiment";
import EvaluationManagement from "@/components/view_mode/evaluation_mode/expert_evaluation/evaluation_management";

export default function EvaluationMode() {
  const [experiment, setExperiment] = useState<Experiment | undefined>(
    undefined
  );
  const [moduleConfigurations, setModuleConfigurations] = useState<
    ModuleConfiguration[] | undefined
  >(undefined);

  return (
    <>
      <h2 className="text-4xl font-bold text-white mb-4">Evaluation Mode</h2>
      <DefineExperiment
        experiment={experiment}
        onChangeExperiment={(experiment) => {
          setExperiment(experiment);
          setModuleConfigurations(undefined);
        }}
      />
      {experiment && (
        <>
          <ConfigureModules
            experiment={experiment}
            moduleConfigurations={moduleConfigurations}
            onChangeModuleConfigurations={setModuleConfigurations}
          />
          {moduleConfigurations && (
            <ConductExperiment
              experiment={experiment}
              moduleConfigurations={moduleConfigurations}
            />
          )}
        </>
      )}
      <h2 className="text-4xl font-bold text-white mb-4">Expert Evaluation</h2>
      <EvaluationManagement />
    </>
  );
}
