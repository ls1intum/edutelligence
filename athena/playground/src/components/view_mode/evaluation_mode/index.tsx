import type { Experiment } from "./define_experiment";

import { useState } from "react";

import DefineExperiment from "./define_experiment";
import ConductExperiment from "./conduct_experiment";

export default function EvaluationMode() {
  const [experiment, setExperiment] = useState<Experiment | undefined>(undefined);

  return (
    <>
      <h2 className="text-4xl font-bold text-white mb-4">Evaluation Mode</h2>
      <DefineExperiment experiment={experiment} onChangeExperiment={setExperiment} />
      {experiment && (<ConductExperiment experiment={experiment} />)}
    </>
  );
}
