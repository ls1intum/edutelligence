import SideBySideHeader from '@/components/expert_evaluation/expert_view/side_by_side_header';
import React, { useEffect, useState } from 'react';
import LikertScaleForm from "@/components/expert_evaluation/expert_view/likert_scale_form";
import { Exercise } from "@/model/exercise";
import { TextSubmission } from "@/model/submission";
import { Metric } from "@/model/metric";
import {
  fetchExpertEvaluationProgress,
  saveExpertEvaluationProgress
} from "@/hooks/playground/expert_evaluation_progress";
import { ExpertEvaluationProgress } from "@/model/expert_evaluation_progress";
import { useRouter } from "next/router";
import { fetchExpertEvaluationConfig } from "@/hooks/playground/expert_evaluation_config";
import { ExpertEvaluationConfig } from "@/model/expert_evaluation_config";
import CongratulationScreen from "@/components/expert_evaluation/expert_view/congratulation_screen";
import WelcomeScreen from "@/components/expert_evaluation/expert_view/welcome_screen";
import ExerciseScreen from "@/components/expert_evaluation/expert_view/exercise_screen";
import ContinueLaterScreen from "@/components/expert_evaluation/expert_view/continue_later_screen";

export default function SideBySideExpertView() {
  const router = useRouter();
  const { expert_evaluation_config_id, expert_id } = router.query as {
    expert_evaluation_config_id: string;
    expert_id: string
  };
  const dataMode = "expert_evaluation";

  const [exercises, setExercises] = useState<Exercise[]>([]);
  const [submissionsLength, setSubmissionsLength] = useState<number>(0);
  const [currentSubmissionIndex, setCurrentSubmissionIndex] = useState<number>(0);
  const [currentExerciseIndex, setCurrentExerciseIndex] = useState<number>(0);
  const [metrics, setMetrics] = useState<Metric[]>([]);
  const [selectedValues, setSelectedValues] = useState<ExpertEvaluationProgress['selected_values']>({});
  const [evaluationStarted, setEvaluationStarted] = useState<boolean>(true);
  const [hasStartedEvaluating, setHasStartedEvaluating] = useState<boolean>(true);
  const [isFinishedEvaluating, setIsFinishedEvaluating] = useState<boolean>(false);
  const [isNewExercise, setIsNewExercise] = useState<boolean>(false);
  const [isContinueLater, setContinueLater] = useState<boolean>(false);
  const [isMarkMissingValues, setMarkMissingVaues] = useState<boolean>(false);

  useEffect(() => {
    const fetchData = async () => {
      if (expert_evaluation_config_id && expert_id) {
        try {
          // Fetch and set data from evaluation config
          const config: ExpertEvaluationConfig = await fetchExpertEvaluationConfig(dataMode, expert_evaluation_config_id);
          setExercises(config.exercises);
          setMetrics(config.metrics);
          setEvaluationStarted(config.started);
        } catch
        (error) {
          console.error('Error loading expert evaluation configuration: ', error);
        }

        try {
          let expertEvaluationProgress = await fetchExpertEvaluationProgress(dataMode, expert_evaluation_config_id, expert_id);
          setCurrentSubmissionIndex(expertEvaluationProgress.current_submission_index);
          setCurrentExerciseIndex(expertEvaluationProgress.current_exercise_index);
          setSelectedValues(expertEvaluationProgress.selected_values);
          setHasStartedEvaluating(expertEvaluationProgress.has_started_evaluating);
          setIsFinishedEvaluating(expertEvaluationProgress.is_finished_evaluating);

        } catch (error) {
          console.error('Error loading expert evaluation progress: ', error);
        }
        setContinueLater(false);
      }
    }
      ; fetchData();
  }, [expert_evaluation_config_id, expert_id]
  );

  useEffect(() => {
    if (exercises && exercises.length > 0) {
      let total_submissions = 0;
      for (const exercise of exercises) {
        if (exercise.submissions) {
          total_submissions += exercise.submissions.length;
        }
      }
      setSubmissionsLength(total_submissions);
    }
  }, [exercises, metrics]);

  const isExerciseComplete = (): boolean => {
    const exerciseData = selectedValues[currentExercise.id];
    if (!exerciseData) return false;

    if (currentSubmission) {
      const submissionData = exerciseData[currentSubmission.id];
      if (!submissionData) return false;
      const currentFeedbacks = currentSubmission.feedbacks;

      if (currentFeedbacks) {
        // Check if all required feedback types and metrics are selected
        for (const feedbackType of Object.keys(currentFeedbacks)) {
          const feedbackData = submissionData[feedbackType];
          if (!feedbackData) return false;

          for (const metric of metrics) {
            if (!(metric.id in feedbackData)) return false;
          }
        }
      }
    }
    return true;
  }

  const currentExercise = exercises[currentExerciseIndex];
  const currentSubmission = currentExercise?.submissions?.[currentSubmissionIndex];
  const globalSubmissionIndex = exercises.slice(0, currentExerciseIndex).reduce((sum, exercise) => sum + exercise.submissions!.length, 0) + currentSubmissionIndex;

  const handleNext = () => {
    let confirmed = true;
    if (!isExerciseComplete()) {
      setMarkMissingVaues(true);
      confirmed = confirm("Are you sure want to continue with the next submission? You did not yet evaluate all metrics!");
    }

    if (globalSubmissionIndex === submissionsLength - 1 && confirmed) {
      confirmed = confirm("Are you sure you want to finish the evaluation? Once you finish, you can no longer make any changes!");
    }

    if (confirmed) {
      const currentExercise = exercises[currentExerciseIndex];
      // If we are at the last submission for the current exercise, go to the next exercise
      if (currentSubmissionIndex < currentExercise.submissions!.length - 1) {
        setCurrentSubmissionIndex((prevIndex) => prevIndex + 1);

      } else if (currentExerciseIndex < exercises.length - 1) {
        // Move to the next exercise, reset submission index
        setCurrentExerciseIndex((prevIndex) => prevIndex + 1);
        setCurrentSubmissionIndex(0);
        setIsNewExercise(true);

      } else {
        setIsFinishedEvaluating(true);
      }
      setMarkMissingVaues(false);
    }
  };

  useEffect(() => {
    saveProgress();
  }, [currentSubmissionIndex, currentExerciseIndex, isFinishedEvaluating]);

  const handlePrevious = () => {
    // If we are not at the first submission, just decrement the submission index
    if (currentSubmissionIndex > 0) {
      setCurrentSubmissionIndex((prevIndex) => prevIndex - 1);


    } else if (currentExerciseIndex > 0) {
      setCurrentExerciseIndex((prevIndex) => prevIndex - 1);
      // Set the submission index to the last submission of the previous exercise
      const previousExercise = exercises[currentExerciseIndex - 1];
      setCurrentSubmissionIndex(previousExercise.submissions!.length - 1);
    }
  };


  const handleWelcomeClose = () => {
    setHasStartedEvaluating(false);
    saveProgress();
  };

  const handleNextExercise = () => {
    setIsNewExercise(false);
  }

  const handleCloseContinueLater = () => {
    setContinueLater(false);
  }

  const handleOpenContinueLater = () => {
    saveProgress();
    setContinueLater(true);
  }

  const saveProgress = () => {
    if (expert_evaluation_config_id && expert_id) {
      setHasStartedEvaluating(true);
      const progress: ExpertEvaluationProgress = {
        current_submission_index: currentSubmissionIndex,
        current_exercise_index: currentExerciseIndex,
        selected_values: selectedValues,
        has_started_evaluating: true,
        is_finished_evaluating: isFinishedEvaluating,
      };
      saveExpertEvaluationProgress(dataMode, expert_evaluation_config_id, expert_id, progress);
    }
  }

  const handleLikertValueChange = (feedbackType: string, metricId: string, value: number) => {
    const exerciseId = currentExercise.id.toString();
    let submissionId = "";
    if (currentExercise.submissions) {
      submissionId = currentExercise.submissions[currentSubmissionIndex].id.toString();
    }

    setSelectedValues((prevValues) => ({
      ...prevValues,
      [exerciseId]: {
        ...prevValues[exerciseId],
        [submissionId]: {
          ...prevValues[exerciseId]?.[submissionId],
          [feedbackType]: {
            ...prevValues[exerciseId]?.[submissionId]?.[feedbackType],
            [metricId]: value
          }
        }
      }
    }));
  }

  if (!exercises && !metrics) {
    return <div className={"bg-white p-6 text-red-600"}>
      Could not fetch config data for expert evaluation (id={expert_evaluation_config_id})
    </div>;
  }

  if (!currentSubmissionIndex && !currentExerciseIndex && !selectedValues) {
    return <div className={"bg-white p-6 text-red-600"}>
      Could not find expert (id={expert_id}) belonging to expert evaluation (id={expert_evaluation_config_id}).
    </div>;
  }

  if (!evaluationStarted) {
    return <div className={"bg-white p-6 text-red-600"}>The expert evaluation (id={expert_evaluation_config_id})
      has not yet started.</div>;
  }

  if (!hasStartedEvaluating) {
    return <WelcomeScreen exercise={currentExercise} onClose={handleWelcomeClose} />;
  }

  if (isContinueLater) {
    return <ContinueLaterScreen onClose={handleCloseContinueLater} />
  }


  if (isNewExercise) {
    return <ExerciseScreen
      onCloseExerciseDetail={handleNextExercise}
      onOpenContinueLater={handleOpenContinueLater}
      exercise={currentExercise}
      currentExerciseIndex={currentExerciseIndex}
      totalExercises={exercises.length}
    />;
  }

  if (isFinishedEvaluating) {
    return <CongratulationScreen />;
  }

  if (currentExercise && currentSubmission && currentSubmission.feedbacks) {
    return (
      <div className={"bg-white p-6"}>
        <SideBySideHeader
          exercise={exercises[currentExerciseIndex]}
          globalSubmissionIndex={globalSubmissionIndex}
          totalSubmissions={submissionsLength}
          onNext={handleNext}
          onPrevious={handlePrevious}
          metrics={metrics}
          onContinueLater={handleOpenContinueLater}
        />
        <LikertScaleForm submission={currentSubmission as TextSubmission}
          exercise={currentExercise}
          feedback={currentSubmission.feedbacks}
          metrics={metrics}
          selectedValues={selectedValues}
          onLikertValueChange={handleLikertValueChange}
          isMarkMissingValue={isMarkMissingValues} />
      </div>
    );
  } else {
    return <div>Loading...</div>;
  }
}
