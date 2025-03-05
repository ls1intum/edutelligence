import type { ExerciseType } from "./exercise";
import { CategorizedFeedback } from "@/model/feedback";

type SubmissionBase = {
    id: number;
    type: ExerciseType; // Playground only
    exercise_id: number;
    feedbacks?: CategorizedFeedback; // Playground only
    meta: {
        [key: string]: any;
    };
};

export type TextSubmission = SubmissionBase & {
  type: "text";
  text: string;
};

export type ProgrammingSubmission = SubmissionBase & {
  type: "programming";
  repository_uri: string;
};

export type ModelingSubmission = SubmissionBase & {
  type: "modeling";
  model: string;
};

export type Submission = ProgrammingSubmission | TextSubmission | ModelingSubmission;
