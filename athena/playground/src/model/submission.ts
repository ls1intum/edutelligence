type SubmissionBase = {
    id: number;
    exercise_id: number;
    student_id: number;
    meta: {
        [key: string]: any;
    };
};

export type TextSubmission = SubmissionBase & {
    content: string;
};

export type ProgrammingSubmission = SubmissionBase & {
    repository_url: string;
};

export type Submission = ProgrammingSubmission | TextSubmission;