import type { Exercise } from "@/model/exercise";
import type { ExecutionMode } from "@/components/selectors/experiment_execution_mode_select";
import type { ExperimentSubmissions } from "@/components/selectors/experiment_submissions_select";

import { useEffect, useState } from "react";

import { useBaseInfo } from "@/hooks/base_info_context";

import ExerciseTypeSelect from "@/components/selectors/exercise_type_select";
import ExerciseSelect from "@/components/selectors/exercise_select";
import ExerciseDetail from "@/components/details/exercise_detail";
import ExperimentExecutionModeSelect from "@/components/selectors/experiment_execution_mode_select";
import ExperimentSubmissionsSelect from "@/components/selectors/experiment_submissions_select";

type Experiment = {
  dataMode: string;
  exerciseType: string;
  exercise: Exercise;
  executionMode: ExecutionMode;
  experimentSubmissions: ExperimentSubmissions;
};

type ExperimentExport = {
  dataMode: string;
  exerciseType: string;
  exerciseId: number;
  executionMode: ExecutionMode;
  experimentSubmissions: {
    trainingSubmissionIds: number[] | undefined;
    testSubmissionIds: number[];
  };
};

export default function DefineExperiment() {
  const { dataMode } = useBaseInfo();
  const [exerciseType, setExerciseType] = useState<string | undefined>(
    undefined
  );
  const [exercise, setExercise] = useState<Exercise | undefined>(undefined);
  const [executionMode, setExecutionMode] = useState<ExecutionMode | undefined>(
    undefined
  );
  const [experimentSubmissions, setExperimentSubmissions] = useState<
    ExperimentSubmissions | undefined
  >(undefined);

  useEffect(() => {
    setExerciseType(undefined);
  }, [dataMode]);
  useEffect(() => {
    setExercise(undefined);
  }, [exerciseType]);
  useEffect(() => {
    setExperimentSubmissions(undefined);
  }, [exercise]);

  const getExperiment = (): Experiment | undefined => {
    if (
      !dataMode ||
      !exerciseType ||
      !exercise ||
      !executionMode ||
      !experimentSubmissions ||
      !experimentSubmissions.testSubmissions
    ) {
      return undefined;
    }
    return {
      dataMode,
      exerciseType,
      exercise,
      executionMode,
      experimentSubmissions,
    };
  };

  const experiment = getExperiment();

  const getExperimentExport = (experiment: Experiment): ExperimentExport => {
    return {
      dataMode: experiment.dataMode,
      exerciseType: experiment.exerciseType,
      exerciseId: experiment.exercise.id,
      executionMode: experiment.executionMode,
      experimentSubmissions: {
        trainingSubmissionIds:
          experiment.experimentSubmissions.trainingSubmissions &&
          experiment.experimentSubmissions.trainingSubmissions.map((s) => s.id),
        testSubmissionIds: experiment.experimentSubmissions.testSubmissions.map(
          (s) => s.id
        ),
      },
    };
  };

  return (
    <div className="bg-white rounded-md p-4 mb-8 space-y-2">
      <h3 className="text-2xl font-bold">Define Experiment</h3>
      <ExperimentExecutionModeSelect
        executionMode={executionMode}
        onChangeExecutionMode={setExecutionMode}
      />
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
      <ExperimentSubmissionsSelect
        exercise={exercise}
        experimentSubmissions={experimentSubmissions}
        onChangeExperimentSubmissions={setExperimentSubmissions}
      />
      {experiment && (
        <a
          className="text-primary-500"
          href={`data:text/json;charset=utf-8,${encodeURIComponent(
            JSON.stringify(getExperimentExport(experiment), null, 2)
          )}`}
          download={"experiment.json"}
        >
          Export
        </a>
      )}
    </div>
  );
}
