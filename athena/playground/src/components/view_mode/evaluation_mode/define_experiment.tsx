import type { Exercise } from "@/model/exercise";
import type { Submission } from "@/model/submission";
import type { DataMode } from "@/model/data_mode";
import type { Feedback } from "@/model/feedback";
import type { ExecutionMode } from "@/components/selectors/experiment_execution_mode_select";

import { useEffect, useState } from "react";
import { twMerge } from "tailwind-merge";

import { useBaseInfo, useBaseInfoDispatch } from "@/hooks/base_info_context";
import { fetchExercises } from "@/hooks/playground/exercises";
import { fetchSubmissions } from "@/hooks/playground/submissions";

import ExerciseTypeSelect from "@/components/selectors/exercise_type_select";
import ExerciseSelect from "@/components/selectors/exercise_select";
import ExerciseDetail from "@/components/details/exercise_detail";
import ExperimentExecutionModeSelect from "@/components/selectors/experiment_execution_mode_select";
import ExperimentSubmissionsSelect from "@/components/selectors/experiment_submissions_select";
import useFeedbacks from "@/hooks/playground/feedbacks";


export type Experiment = {
  dataMode: DataMode;
  exerciseType: string;
  exercise: Exercise;
  executionMode: ExecutionMode;
  trainingSubmissions?: Submission[];
  evaluationSubmissions: Submission[];
  tutorFeedbacks: Feedback[];
};

type ExperimentExport = {
  dataMode: DataMode;
  exerciseType: string;
  exerciseId: number;
  executionMode: ExecutionMode;
  trainingSubmissionIds: number[] | undefined;
  evaluationSubmissionIds: number[];
};

type DefineExperimentProps = {
  experiment: Experiment | undefined;
  onChangeExperiment: (experiment: Experiment | undefined) => void;
};

export default function DefineExperiment({
  experiment,
  onChangeExperiment,
}: DefineExperimentProps) {
  const baseInfoDispatch = useBaseInfoDispatch();
  const { dataMode } = useBaseInfo();
  const [exerciseType, setExerciseType] = useState<string | undefined>(undefined);
  const [exercise, setExercise] = useState<Exercise | undefined>(undefined);
  const [executionMode, setExecutionMode] = useState<ExecutionMode | undefined>("batch");
  const [trainingSubmissions, setTrainingSubmissions] = useState<Submission[] | undefined>(undefined);
  const [evaluationSubmissions, setEvaluationSubmissions] = useState<Submission[] | undefined>(undefined);
  const [isImporting, setIsImporting] = useState<boolean>(false);
  const { data: feedbacks, isLoading: isLoadingFeedbacks, isError: isErrorFeedbacks } = useFeedbacks(exercise);

  useEffect(() => {
    setExerciseType(undefined);
  }, [dataMode]);
  useEffect(() => {
    setExercise(undefined);
  }, [exerciseType]);
  useEffect(() => {
    setTrainingSubmissions(undefined);
    setEvaluationSubmissions(undefined);
  }, [exercise]);

  const getExperiment = (): Experiment | undefined => {
    if (
      !dataMode ||
      !exerciseType ||
      !exercise ||
      !executionMode ||
      !evaluationSubmissions ||
      !evaluationSubmissions ||
      evaluationSubmissions.length === 0 ||
      isLoadingFeedbacks ||
      isErrorFeedbacks
    ) {
      return undefined;
    }
    return {
      dataMode,
      exerciseType,
      exercise,
      executionMode,
      trainingSubmissions,
      evaluationSubmissions,
      tutorFeedbacks: feedbacks || [],
    };
  };

  const definedExperiment = getExperiment();

  const getExperimentExport = (experiment: Experiment): ExperimentExport => {
    return {
      dataMode: experiment.dataMode,
      exerciseType: experiment.exerciseType,
      exerciseId: experiment.exercise.id,
      executionMode: experiment.executionMode,
      trainingSubmissionIds:
        experiment.trainingSubmissions &&
        experiment.trainingSubmissions.map((s) => s.id),
      evaluationSubmissionIds: experiment.evaluationSubmissions.map(
        (s) => s.id
      ),
      // tutor feedback ids are not important for the export
    };
  };

  const importExperiment = async (fileContent: string) => {
    const experimentExport = JSON.parse(fileContent) as ExperimentExport;
    const {
      dataMode,
      exerciseType,
      exerciseId,
      executionMode,
      trainingSubmissionIds,
      evaluationSubmissionIds,
    } = experimentExport;
    if (
      !dataMode ||
      !exerciseType ||
      !exerciseId ||
      !executionMode ||
      !evaluationSubmissionIds
    ) {
      console.error("Invalid experiment export");
      return;
    }
    console.log("Importing experiment", experimentExport);

    baseInfoDispatch({ type: "SET_DATA_MODE", payload: dataMode });
    setExerciseType(exerciseType);
    setExecutionMode(executionMode);
    const exercises = await fetchExercises(dataMode);
    const exercise = exercises?.find((e) => e.id === exerciseId);
    setExercise(exercise);
    if (exercise) {
      const submissions = await fetchSubmissions(exercise, dataMode);
      const trainingSubmissions = trainingSubmissionIds
        ? submissions.filter((s) =>
            trainingSubmissionIds?.includes(s.id)
          )
        : undefined;
      const evaluationSubmissions = submissions.filter((s) =>
        evaluationSubmissionIds?.includes(s.id)
      );
      setTrainingSubmissions(trainingSubmissions);
      setEvaluationSubmissions(evaluationSubmissions);
    } else {
      setTrainingSubmissions(undefined);
      setEvaluationSubmissions(undefined);
    }
  };

  return (
    <div className="bg-white rounded-md p-4 mb-8 space-y-2">
      <div className="flex flex-row justify-between items-center">
        <h3 className="text-2xl font-bold">Define Experiment</h3>
        <div className="flex flex-row">
          {definedExperiment && (
            <a
              className="rounded-md p-2 text-primary-500 hover:text-primary-600 hover:bg-gray-100 hover:no-underline"
              href={`data:text/json;charset=utf-8,${encodeURIComponent(
                JSON.stringify(getExperimentExport(definedExperiment), null, 2)
              )}`}
              download={"experiment.json"}
            >
              Export
            </a>
          )}
          <label
            className={twMerge(
              "rounded-md p-2",
              isImporting || experiment !== undefined
                ? "text-gray-500 cursor-not-allowed"
                : "text-primary-500 hover:text-primary-600 hover:bg-gray-100"
            )}
          >
            Import
            <input
              disabled={isImporting || experiment !== undefined}
              className="hidden"
              type="file"
              accept=".json"
              onChange={(e) => {
                if (e.target.files && e.target.files.length > 0) {
                  setIsImporting(true);
                  const file = e.target.files[0];
                  const reader = new FileReader();
                  reader.onload = (e) => {
                    if (e.target && typeof e.target.result === "string") {
                      importExperiment(e.target.result).finally(() => {
                        setIsImporting(false);
                      });
                    }
                  };
                  reader.readAsText(file);
                }
              }}
            />
          </label>
        </div>
      </div>
      {isImporting ? (
        <p className="text-gray-500">Importing experiment...</p>
      ) : (
        <>
          <ExperimentExecutionModeSelect
            disabled={experiment !== undefined}
            executionMode={executionMode}
            onChangeExecutionMode={setExecutionMode}
          />
          <ExerciseTypeSelect
            disabled={experiment !== undefined}
            exerciseType={exerciseType}
            onChangeExerciseType={setExerciseType}
          />
          {exerciseType && (
            <>
              <ExerciseSelect
                disabled={experiment !== undefined}
                exercise={exercise}
                exerciseType={exerciseType}
                onChange={setExercise}
              />
              {exercise && <ExerciseDetail exercise={exercise} />}
            </>
          )}
          <ExperimentSubmissionsSelect
            disabled={experiment !== undefined}
            exercise={exercise}
            trainingSubmissions={trainingSubmissions}
            evaluationSubmissions={evaluationSubmissions}
            onChangeTrainingSubmissions={setTrainingSubmissions}
            onChangeEvaluationSubmissions={setEvaluationSubmissions}
          />
        </>
      )}
      <div className="flex flex-row gap-2">
        <button
          className={twMerge(
            "bg-primary-500 text-white rounded-md p-2 mt-2 hover:bg-primary-600 disabled:text-gray-500 disabled:bg-gray-200 disabled:cursor-not-allowed",
            experiment
              ? "disabled:bg-green-100 disabled:text-green-600"
              : "disabled:text-gray-500 disabled:bg-gray-200"
          )}
          disabled={!definedExperiment || experiment !== undefined}
          onClick={() => {
            if (definedExperiment) {
              onChangeExperiment(definedExperiment);
            }
          }}
        >
          {experiment ? "Experiment Defined" : "Define Experiment"}
        </button>
        {experiment && (
          <button
            className="bg-red-500 text-white rounded-md p-2 mt-2 hover:bg-red-600"
            onClick={() => {
              if (experiment && confirm("Cancel experiment?")) {
                onChangeExperiment(undefined);
              }
            }}
          >
            Cancel
          </button>
        )}
      </div>
    </div>
  );
}
