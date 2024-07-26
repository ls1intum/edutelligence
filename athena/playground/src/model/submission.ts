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
