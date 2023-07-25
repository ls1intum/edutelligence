import type { Feedback } from "@/model/feedback";

import { formatReference } from "@/model/feedback";

export default function FeedbackDetail({ feedback }: { feedback: Feedback; }) {
  return (
    <div className="p-4 bg-white rounded shadow-sm border border-slate-200">
      <label className="block text-sm font-medium text-slate-500">
        {feedback.title ? feedback.title : <i>Missing title</i>}
        <span className="ml-1 font-normal text-sm text-slate-500">
          ({feedback.credits} credits, references {formatReference(feedback)})
        </span>
      </label>
      <p className="mt-1 text-sm text-slate-900 whitespace-pre-wrap">
        {feedback.description ? feedback.description : <i>Missing detail text</i>}
      </p>
    </div>
  );
}
