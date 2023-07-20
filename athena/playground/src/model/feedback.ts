type FeedbackBase = {
  id: number;
  title: string;
  description: string;
  credits: number;
  exercise_id: number;
  submission_id: number;
  meta: {
    [key: string]: any;
  };
};

export type TextFeedback = FeedbackBase & {
  index_start?: number;
  index_end?: number;
};

export type ProgrammingFeedback = FeedbackBase & {
  file_path?: string;
  line_start?: number;
  line_end?: number;
};

export type Feedback = TextFeedback | ProgrammingFeedback;