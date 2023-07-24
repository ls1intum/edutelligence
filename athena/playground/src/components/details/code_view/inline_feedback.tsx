import { Feedback, formatReference } from "@/model/feedback";
import { twMerge } from "tailwind-merge";

type InlineFeedbackProps = {
  feedback: Feedback;
  onFeedbackChange?: (feedback: Feedback) => void;
};

export default function InlineFeedback({
  feedback,
  onFeedbackChange,
}: InlineFeedbackProps) {
  return (
    <div className="m-2 border border-gray-300 rounded-lg text-sm max-w-3xl">
      <div className="flex items-center justify-start px-4 py-2 border-b border-gray-300 text-xs text-gray-600">
        Feedback on {formatReference(feedback)}
      </div>
      <div className="flex justify-start items-center space-x-2 px-4 py-2">
        <div className={twMerge("font-medium rounded px-2.5 py-0.5", feedback.credits < 0 ? "bg-red-100 text-red-800" : feedback.credits > 0 ? "bg-green-100 text-green-800" : "bg-gray-100 text-gray-800")}>
          {feedback.credits}&nbsp;P          
        </div>
        <div className="w-full">
          <div className="flex items-center space-x-1">
            <span className="font-semibold">
              {feedback.title ? feedback.title : <i>Missing title</i>}
            </span>
            <span className="text-xs text-gray-500 rounded-full px-2 py-0.5 bg-gray-100">
              Suggestion
            </span>
          </div>
          <div>
            {feedback.description ? feedback.description : <i>Missing description</i>}
          </div>
        </div>
        <div className="flex flex-col space-y-1">
          <button className="bg-yellow-100 text-yellow-800 rounded px-2 py-0.5 hover:bg-yellow-200 hover:text-yellow-900">
            Edit
          </button>
          <button className="bg-red-100 text-red-800 rounded px-2 py-0.5 hover:bg-red-200 hover:text-red-900">
            Delete
          </button>
        </div>
      </div>
    </div>
  );
}
