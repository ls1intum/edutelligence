import type { IRange } from "monaco-editor";
import type { ExerciseType } from "./exercise";

type FeedbackBase = {
  id?: number;
  type: ExerciseType; // Playground only
  title: string;
  description: string;
  credits: number;
  exercise_id: number;
  submission_id: number;
  is_suggestion?: boolean; // Playground only
  meta: {
    [key: string]: any;
  };
};

export type TextFeedback = FeedbackBase & {
  type: "text";
  index_start?: number;
  index_end?: number;
};

export type ProgrammingFeedback = FeedbackBase & {
  type: "programming";
  file_path?: string;
  line_start?: number;
  line_end?: number;
};

export type Feedback = TextFeedback | ProgrammingFeedback;

export function formatReference(feedback: Feedback): string {
  if (feedback.type === "text") {
    if (feedback.index_start !== undefined && feedback.index_end !== undefined) {
      return `(${feedback.index_start}-${feedback.index_end})`;
    }
  } else if (feedback.type === "programming") {
    if (feedback.file_path !== undefined && feedback.line_start !== undefined) {
      return `file:${feedback.file_path}_line:${feedback.line_start}${feedback.line_end !== undefined ? "-" + feedback.line_end : ""}`;
    } else if (feedback.file_path !== undefined) {
      return `file:${feedback.file_path}`;
    }
  }
  return "";
}

/**
 * Returns the range of the feedback in the given content (for monaco editor)
 * 
 * @param content - the content of the editor
 * @param feedback - the feedback
 * @returns the range of the feedback in the given content
 */
export function getFeedbackRange(content: string, feedback: Feedback): IRange | undefined {
  if (feedback.type === "programming") {
    if (feedback.line_start === undefined && feedback.line_end === undefined) {
      return undefined;
    }
    return {
      startLineNumber: (feedback.line_start || feedback.line_end)!,
      startColumn: 0,
      endLineNumber: (feedback.line_start || feedback.line_end)!,
      endColumn: Infinity,
    }
  } else if (feedback.type === "text") {
    if (feedback.index_start === undefined && feedback.index_end === undefined) {
      return undefined;
    }
    const linesBeforeStart = content.slice(0, feedback.index_start ?? feedback.index_end).split("\n");
    const linesBeforeEnd = content.slice(0, feedback.index_end ?? feedback.index_start).split("\n");
    return {
      startLineNumber: linesBeforeStart.length,
      startColumn: linesBeforeStart[linesBeforeStart.length - 1].length + 1,
      endLineNumber: linesBeforeEnd.length,
      endColumn: linesBeforeEnd[linesBeforeEnd.length - 1].length + 1 ,
    }
  }
  return undefined;
}