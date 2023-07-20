type Feedback = {
  id: number;
  exercise_id: number;
  submission_id: number;
  text?: string;
  detail_text?: string;
  index_start: number;
  index_end: number;
  reference?: string;
  credits: number;
  meta: {
    [key: string]: any;
  };
};

export default Feedback;


type FeedbackBase = {
  id: number;
  detail_text: string;
  text: string;
  credits: number;
  meta: {
    [key: string]: any;
  };
  exercise_id: number;
  submission_id: number;
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