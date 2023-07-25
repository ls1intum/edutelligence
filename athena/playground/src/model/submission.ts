import type { ExerciseType } from "./exercise";

type SubmissionBase = {
    id: number;
    type: ExerciseType; // Playground only
    exercise_id: number;
    meta: {
        [key: string]: any;
    };
};

export type TextSubmission = SubmissionBase & {
  type: "text";
  content: string;
};

export type ProgrammingSubmission = SubmissionBase & {
  type: "programming";
  repository_url: string;
};

export type Submission = ProgrammingSubmission | TextSubmission;
