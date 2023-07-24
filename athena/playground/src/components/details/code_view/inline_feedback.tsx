import { Feedback, formatReference } from "@/model/feedback";
import { useState } from "react";
import { twMerge } from "tailwind-merge";
import TextareaAutosize from "react-textarea-autosize";

type InlineFeedbackProps = {
  feedback: Feedback;
  onFeedbackChange?: (feedback: Feedback | undefined) => void;
};

export default function InlineFeedback({
  feedback: propsFeedback,
  onFeedbackChange: propsOnFeedbackChange,
}: InlineFeedbackProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [feedback, onFeedbackChange] = useState<Feedback | undefined>(
    propsFeedback
  );

  if (!feedback) {
    return null;
  }

  return (
    <div className="m-2 border border-gray-300 rounded-lg text-sm max-w-3xl">
      <div className="flex items-center justify-start px-4 py-2 border-b border-gray-300 text-xs text-gray-600">
        Feedback on {formatReference(feedback)}
      </div>
      <div className="flex justify-start items-start space-x-2 px-4 py-2">
        {isEditing ? (
          <input
            className={twMerge(
              "font-medium rounded pl-2.5 py-0.5 w-16 mt-2 border border-gray-300",
              feedback.credits < 0
                ? "bg-red-100 text-red-800"
                : feedback.credits > 0
                ? "bg-green-100 text-green-800"
                : "bg-gray-100 text-gray-800"
            )}
            type="number"
            step="0.5"
            value={feedback.credits}
            onChange={(e) => {
              onFeedbackChange({
                ...feedback,
                credits: e.target.value == "" ? 0 : parseFloat(e.target.value),
              });
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
            {isEditing ? (
              <input
                className="font-semibold w-full border border-gray-300 rounded p-1"
                value={feedback.title}
                placeholder="Title..."
                onChange={(e) =>
                  onFeedbackChange({ ...feedback, title: e.target.value })
                }
              />
            ) : (
              <span className="font-semibold">
                {feedback.title ? feedback.title : <i>Missing title</i>}
              </span>
            )}
            <span className="text-xs text-gray-500 rounded-full px-2 py-0.5 bg-gray-100">
              Suggestion
            </span>
          </div>
          <div>
            {isEditing ? (
              <TextareaAutosize
                className="w-full border border-gray-300 rounded p-1 mt-1"
                value={feedback.description}
                placeholder="Description..."
                onChange={(e) =>
                  onFeedbackChange({
                    ...feedback,
                    description: e.target.value,
                  })
                }
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
              onClick={() => {
                if (confirmDelete) {
                  onFeedbackChange(undefined);
                } else {
                  setConfirmDelete(true);
                  setTimeout(() => setConfirmDelete(false), 2000);
                }
              }}
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
              onClick={() => {
                setIsEditing(!isEditing);
                setConfirmDelete(false);
              }}
            >
              {isEditing ? "Save" : "Edit"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
