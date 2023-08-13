import type { Experiment } from "./define_experiment";
import type { ModuleConfiguration } from "./configure_modules";

import { useState } from "react";

import DefineExperiment from "./define_experiment";
import ConfigureModules from "./configure_modules";
import ConductExperiment from "./conduct_experiment";
import { ModuleProvider } from "@/hooks/module_context";

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
        onChangeExperiment={setExperiment}
      />
      {experiment && (
        <>
          <ConfigureModules
            experiment={experiment}
            moduleConfigurations={moduleConfigurations}
            onChangeModuleConfigurations={setModuleConfigurations}
          />
          {moduleConfigurations && (
            // Put the submission selector module in the context
            <ModuleProvider
              module={moduleConfigurations[0].moduleAndConfig.module}
              moduleConfig={moduleConfigurations[0].moduleAndConfig.moduleConfig}
            >
              <ConductExperiment
                experiment={experiment}
                moduleConfigurations={moduleConfigurations}
              />
            </ModuleProvider>
          )}
        </>
      )}
    </>
  );
}
