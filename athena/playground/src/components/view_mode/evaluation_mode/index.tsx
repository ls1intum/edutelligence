import type { Experiment } from "./define_experiment";
import type { ModuleConfiguration } from "./configure_modules";

import { useState } from "react";

import DefineExperiment from "./define_experiment";
import ConfigureModules from "./configure_modules";
import ConductExperiment from "./conduct_experiment";

export default function EvaluationMode() {
  const [experiment, setExperiment] = useState<Experiment | undefined>(undefined);
  const [moduleConfigurations, setModuleConfigurations] = useState<ModuleConfiguration[] | undefined>(undefined);

  return (
    <>
      <h2 className="text-4xl font-bold text-white mb-4">Evaluation Mode</h2>
      <DefineExperiment experiment={experiment} onChangeExperiment={setExperiment} />
      {experiment && (<ConfigureModules experiment={experiment} moduleConfigurations={moduleConfigurations} onChangeModuleConfigurations={setModuleConfigurations} />)}
      {/* {experiment && (<ConductExperiment experiment={experiment} />)} */}
    </>
  );
}
