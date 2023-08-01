import type { Exercise } from "@/model/exercise";

import { useEffect, useState } from "react";

import { useBaseInfo } from "@/hooks/base_info_context";

import DefineExperiment from "./define_experiment";

export default function EvaluationMode() {
  const { dataMode } = useBaseInfo();
  const [exerciseType, setExerciseType] = useState<string | undefined>(undefined);
  const [exercise, setExercise] = useState<Exercise | undefined>(undefined);

  useEffect(() => setExerciseType(undefined), [dataMode]);
  useEffect(() => setExercise(undefined), [exerciseType, dataMode]);

  return (
    <>
      <h2 className="text-4xl font-bold text-white mb-4">Evaluation Mode</h2>
      <DefineExperiment />
    </>
  );
}
