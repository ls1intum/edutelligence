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

export function isTextFeedback(feedback: Feedback): feedback is TextFeedback {
  const textFeedback = feedback as TextFeedback;
  return textFeedback.index_start !== undefined || textFeedback.index_end !== undefined;
}

export function isProgrammingFeedback(feedback: Feedback): feedback is ProgrammingFeedback {
  const programmingFeedback = feedback as ProgrammingFeedback;
  return (
    programmingFeedback.file_path !== undefined ||
    programmingFeedback.line_start !== undefined ||
    programmingFeedback.line_end !== undefined
  );
}

export function formatReference(feedback: Feedback): string {
  if (isTextFeedback(feedback)) {
    if (feedback.index_start !== undefined && feedback.index_end !== undefined) {
      return `(${feedback.index_start}-${feedback.index_end})`;
    }
  } else if (isProgrammingFeedback(feedback)) {
    if (feedback.file_path !== undefined && feedback.line_start !== undefined) {
      return `file:${feedback.file_path}_line:${feedback.line_start}${feedback.line_end !== undefined ? "-" + feedback.line_end : ""}`;
    } else if (feedback.file_path !== undefined) {
      return `file:${feedback.file_path}`;
    }
  }
  return "";
}