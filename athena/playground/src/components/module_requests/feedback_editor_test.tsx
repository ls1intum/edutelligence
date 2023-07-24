import type { Submission } from "@/model/submission";
import type { Exercise } from "@/model/exercise";

import { useEffect, useState } from "react";

import ExerciseSelect from "@/components/selectors/exercise_select";
import SubmissionSelect from "@/components/selectors/submission_select";
import Disclosure from "@/components/disclosure";
import ExerciseDetail from "@/components/details/exercise_detail";
import SubmissionDetail from "@/components/details/submission_detail";
import { useFeedbacks } from "@/helpers/client/get_data";

import { ModuleRequestProps } from ".";
import { Feedback } from "@/model/feedback";

export default function FeedbackEditorTest({
  mode,
  module,
}: ModuleRequestProps) {
  const [exercise, setExercise] = useState<Exercise | undefined>(undefined);
  const [submission, setSubmission] = useState<Submission | undefined>(undefined);

  const { feedbacks: loadedFeedbacks, isLoading: isFeedbackLoading, error: feedbackError } = useFeedbacks(mode, exercise);

  const [feedbacks, setFeedbacks] = useState<Feedback[] | undefined>(undefined);

  useEffect(() => {
    if (loadedFeedbacks) {
      setFeedbacks(loadedFeedbacks);
    }
  }, [loadedFeedbacks]);
 
  useEffect(() => {
    setSubmission(undefined);
  }, [exercise]);

  useEffect(() => {
    setExercise(undefined);
  }, [module, mode]);

  return (
    <div className="bg-white rounded-md p-4 mb-8">
      <h3 className="text-2xl font-bold mb-4">Feedback Editor Test</h3>
      <ExerciseSelect
        mode={mode}
        exerciseType={module.type}
        exercise={exercise}
        onChange={setExercise}
      />
      {exercise && (
        <>
          <SubmissionSelect
            mode={mode}
            exercise_id={exercise?.id}
            submission={submission}
            onChange={setSubmission}
          />
          <div className="space-y-1 mt-2">
            <ExerciseDetail exercise={exercise} mode={mode} />
            {submission && (
              <Disclosure title="Submission">
                <SubmissionDetail
                  submission={submission}
                  feedbacks={feedbacks?.filter(
                    (f) => f.submission_id === submission.id
                  )}
                />
              </Disclosure>
            )}
            {isFeedbackLoading && (
              <div className="text-gray-500 text-sm">Loading feedbacks...</div>
            )}
            {feedbackError && (
              <div className="text-red-500 text-sm">
                Failed to load feedbacks
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
