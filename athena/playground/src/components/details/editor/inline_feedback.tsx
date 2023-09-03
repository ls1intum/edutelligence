import type { Feedback } from "@/model/feedback";

import { useEffect, useRef, useState } from "react";
import TextareaAutosize from "react-textarea-autosize";
import { twMerge } from "tailwind-merge";
import { editor } from "monaco-editor";

import {
  formatReference,
  getFeedbackRange,
  getFeedbackReferenceType,
} from "@/model/feedback";

type InlineFeedbackProps = {
  feedback: Feedback;
  onFeedbackChange?: (feedback: Feedback | undefined) => void;
  onFeedbackChangeEvaluation?: (feedback: Feedback) => void;
  model?: editor.ITextModel;
  className?: string;
};

export default function InlineFeedback({
  feedback,
  onFeedbackChange,
  onFeedbackChangeEvaluation,
  model,
  className,
}: InlineFeedbackProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const [credits, setCredits] = useState(feedback.credits);
  const [title, setTitle] = useState(feedback.title);
  const [description, setDescription] = useState(feedback.description);

  const referenceType = getFeedbackReferenceType(feedback);

  // Highlight the feedback range in the editor
  const [isHovering, setIsHovering] = useState(false);
  const lineDecorations = useRef<string[]>([]);
  const hoverLineDecorations = useRef<string[]>([]);

  const currentCredits = isEditing ? credits : feedback.credits;

  useEffect(() => {
    if (!model) return;
    const range = getFeedbackRange(model, feedback);
    if (!range) return;

    const creditsType =
      currentCredits < 0
        ? "negative"
        : currentCredits > 0
        ? "positive"
        : "neutral";

    lineDecorations.current = model.deltaDecorations(lineDecorations.current, [
      {
        options: {
          inlineClassName: `inline-feedback-text ${creditsType}`,
        },
        range,
      },
    ]);

    hoverLineDecorations.current = model.deltaDecorations(
      hoverLineDecorations.current,
      isHovering
        ? [
            {
              options: {
                inlineClassName: `inline-feedback-text highlighted-${creditsType}`,
              },
              range,
            },
          ]
        : []
    );
  }, [feedback, model, credits, isHovering, isEditing]);

  useEffect(() => {
    if (feedback.isNew && onFeedbackChange) {
      setIsEditing(true);
      feedback.isNew = false;
    }
  }, [feedback, onFeedbackChange]);

  useEffect(() => {
    return () => {
      if (!model || model.isDisposed()) return;
      model.deltaDecorations(lineDecorations.current, []);
      model.deltaDecorations(hoverLineDecorations.current, []);
    };
  }, [model]);

  const handleDelete = () => {
    if (!onFeedbackChange) return;

    if (confirmDelete) {
      onFeedbackChange(undefined);
    } else {
      setConfirmDelete(true);
      setTimeout(() => setConfirmDelete(false), 2000);
    }
  };

  const handleEditOrSave = () => {
    if (!onFeedbackChange) return;

    if (isEditing) {
      onFeedbackChange({
        ...feedback,
        credits: credits,
        title: title,
        description: description,
      });
    } else {
      setCredits(feedback.credits);
      setTitle(feedback.title);
      setDescription(feedback.description);
    }
    setIsEditing(!isEditing);
    setConfirmDelete(false);
  };

  return (
    <div
      className={twMerge(
        "mx-2 my-1 border border-gray-300 rounded-lg text-sm max-w-3xl",
        ...(referenceType !== "unreferenced"
          ? [
              "hover:outline outline-2 hover:shadow transition-all duration-200",
              currentCredits < 0
                ? "outline-red-300/50"
                : currentCredits > 0
                ? "outline-green-300/50"
                : "outline-yellow-300/50",
            ]
          : []),
        className
      )}
      onMouseEnter={() => setIsHovering(true)}
      onMouseLeave={() => setIsHovering(false)}
    >
      <div className="flex items-center justify-start px-4 py-2 border-b border-gray-300 text-xs text-gray-600">
        {referenceType === "unreferenced" && "Unreferenced"}
        {"file_path" in feedback &&
          referenceType === "unreferenced_file" &&
          `References ${feedback.file_path}`}
        {referenceType === "referenced" &&
          `References ${formatReference(feedback)}`}
      </div>
      <div className="flex justify-start items-start space-x-2 px-4 py-2">
        {isEditing && onFeedbackChange ? (
          <input
            className={twMerge(
              "font-medium rounded pl-2.5 py-0.5 w-16 mt-2 border border-gray-300",
              (!isEditing && feedback.credits < 0) || (isEditing && credits < 0)
                ? "bg-red-100 text-red-800"
                : (!isEditing && feedback.credits > 0) ||
                  (isEditing && credits > 0)
                ? "bg-green-100 text-green-800"
                : "bg-yellow-100 text-yellow-800"
            )}
            type="number"
            step="0.5"
            value={credits}
            onChange={(e) => {
              setCredits(e.target.value == "" ? 0 : parseFloat(e.target.value));
            }}
          />
        ) : (
          <div
            className={twMerge(
              "font-medium rounded px-2.5 py-0.5 mt-2",
              feedback.credits < 0
                ? "bg-red-100 text-red-800"
                : feedback.credits > 0
                ? "bg-green-100 text-green-800"
                : "bg-yellow-100 text-yellow-800"
            )}
          >
            {feedback.credits}&nbsp;P
          </div>
        )}
        <div className="w-full">
          <div className="flex items-center justify-between space-x-1">
            {isEditing && onFeedbackChange ? (
              <input
                className="font-semibold w-full border border-gray-300 rounded p-1"
                value={title}
                placeholder="Title..."
                onChange={(e) => setTitle(e.target.value)}
              />
            ) : (
              <span className="font-semibold">
                {feedback.title ? feedback.title : <i>Missing title</i>}
              </span>
            )}
            <div className="flex gap-1">
              {feedback.isSuggestion && (
                <span className="text-xs text-violet-800 rounded-full px-2 py-0.5 bg-violet-100">
                  Suggestion
                </span>
              )}
              {feedback.grading_instruction_id && (
                <span className="text-xs text-orange-800 rounded-full px-2 py-0.5 bg-orange-100">
                  Grading Instruction
                </span>
              )}
            </div>
          </div>
          <div>
            {isEditing && onFeedbackChange ? (
              <TextareaAutosize
                className="w-full border border-gray-300 rounded p-1 mt-1"
                value={description}
                placeholder="Description..."
                onChange={(e) => setDescription(e.target.value)}
              />
            ) : feedback.description ? (
              <span className="whitespace-pre-wrap">
                {feedback.description}
              </span>
            ) : (
              <i>Missing description</i>
            )}
          </div>
        </div>
        {onFeedbackChange && (
          <div className="flex flex-col space-y-1 w-24">
            <button
              className={twMerge(
                "bg-red-100 text-red-800 rounded px-2 py-0.5 hover:bg-red-200 hover:text-red-900",
                confirmDelete
                  ? "bg-red-500 text-white hover:bg-red-600 hover:text-white"
                  : ""
              )}
              onClick={handleDelete}
            >
              {confirmDelete ? "Confirm" : "Delete"}
            </button>
            <button
              className={twMerge(
                "rounded px-2 py-0.5",
                isEditing
                  ? "bg-primary-100 text-primary-800 hover:bg-primary-200 hover:text-primary-900"
                  : "bg-yellow-100 text-yellow-800 hover:bg-yellow-200 hover:text-yellow-900"
              )}
              onClick={handleEditOrSave}
            >
              {isEditing ? "Save" : "Edit"}
            </button>
          </div>
        )}
      </div>
      {feedback.evaluation && (
        <div className="flex items-center justify-start px-4 py-2 border-t gap-1 border-gray-300 text-xs text-gray-600">
          {Object.entries(feedback.evaluation).map(([key, value]) => (
            <div
              key={key}
              className="flex flex-col items-center space-x-1 mr-2 gap-1"
            >
              <span className="font-semibold capitalize">{key}</span>
              <div
                className={twMerge(
                  "rounded-md px-2 py-0.5 bg-gray-100 text-gray-800 capitalize",
                  value.correct === true
                    ? "bg-green-200"
                    : value.correct === false
                    ? "bg-red-200"
                    : "bg-gray-100"
                )}
              >
                {value.label}
              </div>
              {onFeedbackChangeEvaluation && (
                <div className="space-x-1">
                  <button
                    className={twMerge(
                      "rounded-md aspect-square p-2",
                      value.correct === true
                        ? "bg-green-400 shadow-md hover:bg-green-500"
                        : "bg-gray-100 hover:bg-green-200 hover:shadow-md"
                    )}
                    onClick={() => {
                      if (value.correct === true) {
                        value.correct = undefined;
                      } else {
                        value.correct = true;
                      }
                      onFeedbackChangeEvaluation(feedback);
                    }}
                  >
                    👍
                  </button>
                  <button
                    className={twMerge(
                      "rounded-md aspect-square p-2 bg-gray-100",
                      value.correct === false
                        ? "bg-red-400 shadow-md hover:bg-red-500"
                        : "hover:bg-red-200 hover:shadow-md"
                    )}
                    onClick={() => {
                      if (value.correct === false) {
                        value.correct = undefined;
                      } else {
                        value.correct = false;
                      }
                      onFeedbackChangeEvaluation(feedback);
                    }}
                  >
                    👎
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
