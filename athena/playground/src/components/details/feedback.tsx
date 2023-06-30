import Feedback from "@/model/feedback";

type FeedbackDetailProps = {
  feedback: Feedback;
};

export default function FeedbackDetail({ feedback }: FeedbackDetailProps) {
  return (
    <div className="p-4 bg-white rounded shadow-sm border border-slate-200">
      <label className="block text-sm font-medium text-slate-500">
        {feedback.text ? feedback.text : <i>Missing title</i>}
        <span className="ml-1 font-normal text-sm text-slate-500">
          ({feedback.credits} credits, references {feedback.reference})
        </span>
      </label>
      <p className="mt-1 text-sm text-slate-900 whitespace-pre-wrap">
        {feedback.detail_text ? feedback.detail_text : <i>Missing detail text</i>}
      </p>
    </div>
  );
}
