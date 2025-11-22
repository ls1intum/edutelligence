import type { IRange, editor } from "monaco-editor";
import type { ExerciseType, StructuredGradingInstruction } from "./exercise";
import type { Submission } from "./submission";

type FeedbackBase = {
  id: number;
  type: ExerciseType; // Playground only
  title?: string;
  description?: string;
  credits: number;
  exercise_id: number;
  submission_id: number;
  structured_grading_instruction_id?: number;
  structured_grading_instruction?: StructuredGradingInstruction; // Playground only
  isSuggestion?: boolean; // Playground only
  isNew?: boolean; // Playground only
  isChanged?: boolean; // Playground only
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

export type ModelingFeedback = FeedbackBase & {
  type: "modeling";
  reference?: string;
};

export type Feedback = TextFeedback | ProgrammingFeedback | ModelingFeedback;

export type CategorizedFeedback = {
  [key: string]: Feedback[];
};

/**
 * Returns the formatted reference of a given feedback. This can be a line range or an element ID depending on the
 * exercise type.
 * @param feedback The Feedback that is connected to the reference that should be formatted.
 */
export function formatReference(feedback: Feedback): string {
  switch (feedback.type) {
    case "text":
      if (
        feedback.index_start !== undefined &&
        feedback.index_end !== undefined
      ) {
        return `${feedback.index_start}-${feedback.index_end}`;
      }
      break;

    case "programming":
      if (feedback.file_path !== undefined && feedback.line_start !== undefined) {
        return `file:${feedback.file_path}_line:${feedback.line_start}${
          feedback.line_end !== undefined ? "-" + feedback.line_end : ""
        }`;
      } else if (feedback.file_path !== undefined) {
        return `file:${feedback.file_path}`;
      }

      break;

    case "modeling":
      if (feedback.reference) {
        return `[${feedback.reference}]`
      }
      break;
    }

    return "";
}

/**
 * Returns the range of the feedback in the given content (for monaco editor)
 *
 * @param model - the monaco editor model
 * @param feedback - the feedback
 * @returns the range of the feedback in the given content
 */
export function getFeedbackRange(
  model: editor.ITextModel,
  feedback: Feedback
): IRange | undefined {

  switch (feedback.type) {
    case "programming":
      if (feedback.line_start === undefined && feedback.line_end === undefined) {
        return undefined;
      }
      return {
        startLineNumber: (feedback.line_start || feedback.line_end)! + 1, // Monaco line numbers are 1-indexed
        startColumn: 0,
        endLineNumber: (feedback.line_end || feedback.line_start)! + 1, // Monaco line numbers are 1-indexed
        endColumn: Infinity,
      };

    case "text":
      if (
        feedback.index_start === undefined &&
        feedback.index_end === undefined
      ) {
        return undefined;
      }
      const startPosition = model.getPositionAt(
        feedback.index_start ?? feedback.index_end!
      );
      const endPosition = model.getPositionAt(
        feedback.index_end ?? feedback.index_start!
      );
      return {
        startLineNumber: startPosition.lineNumber,
        startColumn: startPosition.column,
        endLineNumber: endPosition.lineNumber,
        endColumn: endPosition.column,
      };
    default:
      return undefined;

  }
}

export type FeedbackReferenceType =
  | "unreferenced"
  | "unreferenced_file"
  | "referenced";

/**
 * Returns the reference type of the feedback
 *
 * @param feedback - the feedback
 * @returns the reference type of the feedback
 */
export function getFeedbackReferenceType(feedback: Feedback): FeedbackReferenceType {
  switch (feedback.type) {
    case "programming":
      if (feedback.file_path != undefined && feedback.line_start != undefined) {
        return "referenced";
      } else if (feedback.file_path != undefined) {
        return "unreferenced_file";
      }
      break;

    case "text":
      if (
        feedback.index_start != undefined &&
        feedback.index_end != undefined
      ) {
        return "referenced";
      }
      break;

    case "modeling":
      if (feedback.reference) {
        return "referenced";
      }
      break;
  }

  return "unreferenced";
}

/**
 * Transforms a onFeedbacksChange function to a single onFeedbackChange function for a specific feedback
 *
 * @param feedback - feedback for which the onFeedbackChange function should be created
 * @param feedbacks - feedbacks array
 * @param onFeedbacksChange - onFeedbacksChange function that should be transformed
 * @returns a onFeedbackChange function for the given feedback
 * @example
 *   const onFeedbackChange = createFeedbackItemUpdater(feedback, feedbacks, onFeedbacksChange);
 *   onFeedbackChange(newFeedback);
 */
export function createFeedbackItemUpdater(
  feedback: Feedback,
  feedbacks: Feedback[],
  onFeedbacksChange: (feedbacks: Feedback[]) => void
): (newFeedback: Feedback | undefined) => void {
  return (newFeedback: Feedback | undefined) => {
    let newFeedbacks = [...feedbacks];
    if (newFeedback === undefined) {
      newFeedbacks = newFeedbacks.filter((f) => f.id !== feedback.id);
    } else {
      newFeedback.isChanged = true;
      newFeedbacks = newFeedbacks.map((f) =>
        f.id === feedback.id ? newFeedback : f
      );
    }
    onFeedbacksChange(newFeedbacks);
  };
}

/**
 * Creates a new feedback for the given submission
 * 
 * @param submission - the submission for which a new feedback should be created
 * @returns a new feedback
 */
export const createNewFeedback = (submission: Submission): Feedback => {
  return {
    id: Date.now(), // Good enough for the playground
    credits: 0,
    title: "",
    description: "",
    type: submission.type,
    exercise_id: submission.exercise_id,
    submission_id: submission.id,
    isNew: true,
    meta: {},
  };
};
