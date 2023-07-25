import type { ModuleMeta } from "@/model/health_response";
import type { Exercise } from "@/model/exercise";
import type { Submission } from "@/model/submission";
import type { Feedback } from "@/model/feedback";

import { useEffect, useState } from "react";

import { useBaseInfo } from "@/hooks/base_info_context";
import useFeedbacks from "@/hooks/playground/feedbacks";

import Disclosure from "@/components/disclosure";
import ExerciseSelect from "@/components/selectors/exercise_select";
import SubmissionSelect from "@/components/selectors/submission_select";
import ExerciseDetail from "@/components/details/exercise_detail";
import SubmissionDetail from "@/components/details/submission_detail";

export default function FeedbackEditorTest({
  module,
}: { module: ModuleMeta}) {
  const { mode } = useBaseInfo();

  const [exercise, setExercise] = useState<Exercise | undefined>(undefined);
  const [submission, setSubmission] = useState<Submission | undefined>(
    undefined
  );

  const {
    data: loadedFeedbacks,
    isLoading: isFeedbackLoading,
    error: feedbackError,
  } = useFeedbacks(exercise);

  const [feedbacks, setFeedbacks] = useState<Feedback[]>([]);

  useEffect(() => {
    if (submission && loadedFeedbacks) {
      setFeedbacks(
        loadedFeedbacks.filter((f) => f.submission_id === submission.id)
      );
    }
  }, [submission, loadedFeedbacks]);

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
        exerciseType={module.type}
        exercise={exercise}
        onChange={setExercise}
      />
      {exercise && (
        <>
          <SubmissionSelect
            exercise={exercise}
            submission={submission}
            onChange={setSubmission}
          />
          <div className="space-y-1 mt-2">
            <ExerciseDetail exercise={exercise} />
            {submission && (
              <Disclosure title="Submission Detail">
                <SubmissionDetail
                  submission={submission}
                  feedbacks={feedbacks}
                  onFeedbacksChange={setFeedbacks}
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
