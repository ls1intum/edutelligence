import ExerciseTypeSelect from "@/components/selectors/exercise_type_select";
import useHealth from "@/hooks/health";
import type { Exercise } from "@/model/exercise";
import { HealthResponse } from "@/model/health_response";

import { useState } from "react";

export default function EvaluationMode() {
  const [exerciseType, setExerciseType] = useState<string | undefined>(undefined); // TODO: useExerciseType
  const [exercise, setExercise] = useState<Exercise | undefined>(undefined);
  const { data: healthData, error } = useHealth();

  const healthyModules = (healthResponse: HealthResponse) => {
    return Object.values(healthResponse.modules).filter((module) => module.healthy);
  }

  return (
    <>
      <h2 className="text-4xl font-bold text-white mb-4">Evaluation Mode</h2>
      <div className="bg-white rounded-md p-4 mb-8">
        <h3 className="text-2xl font-bold mb-4">
          Experiment
        </h3>
        <ExerciseTypeSelect exerciseType={exerciseType} onChangeExerciseType={setExerciseType} />
        <p>Select Exercise</p>
        <p>Select mode</p>
        <p>Select Submissions to use</p>
        <p>Import / Export</p>
      </div>
    </>
  );
}
