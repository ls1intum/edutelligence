import type { Feedback } from "@/model/feedback";

import { useEffect, useRef, useState } from "react";
import { twMerge } from "tailwind-merge";
import TextareaAutosize from "react-textarea-autosize";

import {
  formatReference,
  getFeedbackRange,
  getFeedbackReferenceType,
} from "@/model/feedback";
import { editor } from "monaco-editor";

type InlineFeedbackProps = {
  feedback: Feedback;
  onFeedbackChange?: (feedback: Feedback | undefined) => void;
  model?: editor.ITextModel;
  className?: string;
};

export default function InlineFeedback({
  feedback,
  onFeedbackChange,
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

  useEffect(() => {
    if (!model) return;
    const range = getFeedbackRange(model, feedback);
    if (!range) return;

    const currentCredits = isEditing ? credits : feedback.credits;
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
    if (feedback.is_new && onFeedbackChange) {
      setIsEditing(true);
      feedback.is_new = false;
    }
  }, [feedback, onFeedbackChange]);

  useEffect(() => {
    return () => {
      model?.deltaDecorations(lineDecorations.current, []);
      model?.deltaDecorations(hoverLineDecorations.current, []);
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
                : "bg-gray-100 text-gray-800"
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
                : "bg-gray-100 text-gray-800"
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
            {feedback.is_suggestion && (
              <span className="text-xs text-fuchsia-500 rounded-full px-2 py-0.5 bg-fuchsia-100">
                Suggestion
              </span>
            )}
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
    </div>
  );
}
