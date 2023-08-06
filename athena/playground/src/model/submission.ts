type SubmissionBase = {
    id: number;
    exercise_id: number;
    meta: {
        [key: string]: any;
    };
};

export type TextSubmission = SubmissionBase & {
  text: string;
};

export type ProgrammingSubmission = SubmissionBase & {
  repository_url: string;
};

export type Submission = ProgrammingSubmission | TextSubmission;

export function isProgrammingSubmission(submission: Submission): submission is ProgrammingSubmission {
  return (submission as ProgrammingSubmission).repository_url !== undefined;
}

export function isTextSubmission(submission: Submission): submission is TextSubmission {
  return (submission as TextSubmission).text !== undefined;
}