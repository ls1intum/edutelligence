import { Feedback } from "@/model/feedback";

type InlineFeedbackProps = {
  feedback: Feedback;
  onFeedbackChange?: (feedback: Feedback) => void;
};

export default function InlineFeedback({ feedback, onFeedbackChange }: InlineFeedbackProps) {
  return (
    <div>
      Text
    </div>
  );
}