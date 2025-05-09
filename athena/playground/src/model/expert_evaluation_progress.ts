export type ExpertEvaluationProgress = {
  current_submission_index: number;
  current_exercise_index: number;
  selected_values: {
    [exerciseId: string]: { // Group by exercise ID
      [submissionId: string]: { // Group by submission ID within each exercise
        [feedbackType: string]: { // Group by feedback type
          [metricId: string]: number; // Store metric Likert scale values for each feedback type
        };
      };
    };
  };
  has_started_evaluating: boolean;
  is_finished_evaluating: boolean;
};
