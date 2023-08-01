import type { Exercise } from "@/model/exercise";
import type { ExecutionMode } from "@/components/selectors/experiment_execution_mode_select";

import { useEffect, useState } from "react";

import { useBaseInfo } from "@/hooks/base_info_context";

import ExerciseTypeSelect from "@/components/selectors/exercise_type_select";
import ExerciseSelect from "@/components/selectors/exercise_select";
import ExerciseDetail from "@/components/details/exercise_detail";
import ExperimentExecutionModeSelect from "@/components/selectors/experiment_execution_mode_select";

export default function DefineExperiment() {
  const { dataMode } = useBaseInfo();
  const [exerciseType, setExerciseType] = useState<string | undefined>(undefined);
  const [exercise, setExercise] = useState<Exercise | undefined>(undefined);
  const [executionMode, setExecutionMode] = useState<ExecutionMode | undefined>(undefined);

  useEffect(() => setExerciseType(undefined), [dataMode]);
  useEffect(() => setExercise(undefined), [exerciseType, dataMode]);

  return (
    <div className="bg-white rounded-md p-4 mb-8 space-y-2">
      <h3 className="text-2xl font-bold">Experiment</h3>
      <ExerciseTypeSelect
        exerciseType={exerciseType}
        onChangeExerciseType={setExerciseType}
      />
      {exerciseType && (
        <>
          <ExerciseSelect
            exercise={exercise}
            exerciseType={exerciseType}
            onChange={setExercise}
          />
          {exercise && <ExerciseDetail exercise={exercise} />}
        </>
      )}
      {/* 
        Note to self: 
        1. First implement the incremental learning mode + comparison 
        2. Then implement the batch mode (+ comparison)
        3. Train/test split mode (send all feedback for train at first, then test with the incremental learning mode / batch mode)
        */}
      <ExperimentExecutionModeSelect executionMode={executionMode} onChangeExecutionMode={setExecutionMode} />
      <p>Select mode</p>
      <p>Select Submissions to use</p>
      <p>Submissions list (specific to mode)</p>
      <p>Import / Export</p>
    </div>
  );
}
