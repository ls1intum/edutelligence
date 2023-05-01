import {useState} from "react";
import Submission from "@/pages/model/submission";
import { Exercise } from "@/pages/model/exercise";
import ExerciseSelect from "@/pages/components/exercise_select";
import SubmissionSelect from "@/pages/components/submission_select";
import FeedbackSelect from "@/pages/components/feedback_select";
import Feedback from "@/pages/model/feedback";
import ModuleResponse from "@/pages/model/module_response";
import ModuleResponseView from "@/pages/components/module_response_view";

async function sendFeedback(athenaUrl: string, exercise: Exercise | null, submission: Submission | null, feedback: Feedback | null): Promise<ModuleResponse | undefined> {
    if (!exercise) {
        alert("Please select an exercise");
        return;
    }
    if (!submission) {
        alert("Please select a submission");
        return;
    }
    if (!feedback) {
        alert("Please select a feedback");
        return;
    }
    try {
        const athenaFeedbackUrl = `${athenaUrl}/feedback`;
        const response = await fetch(`/api/athena_request?${new URLSearchParams({ url: athenaFeedbackUrl })}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ exercise, submission, feedback })
        });
        if (response.status !== 200) {
            console.error(response);
            alert(`Athena responded with status code ${response.status}`);
            return {
                module_name: "Unknown",
                status: response.status,
                data: await response.text()
            };
        }
        alert("Feedback sent successfully!");
        return await response.json();
    } catch (e) {
        console.error(e);
        alert("Failed to send feedback to Athena: Failed to fetch. Is the URL correct?");
    }
}

export default function SendFeedback({ athenaUrl }: { athenaUrl: string }) {
    const [exercise, setExercise] = useState<Exercise | null>(null);
    const [submission, setSubmission] = useState<Submission | null>(null);
    const [feedback, setFeedback] = useState<Feedback | null>(null);
    const [loading, setLoading] = useState<boolean>(false);
    const [response, setResponse] = useState<ModuleResponse | undefined>(undefined);

    return (
        <div className="bg-white rounded-md p-4 mt-8">
            <h1 className="text-2xl font-bold mb-4">Send Feedback to Athena</h1>
            <p className="text-gray-500 mb-4">
                Send a single given feedback to Athena.
                This usually happens when someone gives feedback on the submission in the LMS.
                The matching module for the exercise will receive the feedback at the function annotated with <code>@feedback_consumer</code>.
            </p>
            <ExerciseSelect exercise={exercise} onChange={setExercise} />
            <SubmissionSelect exercise_id={exercise?.id} submission={submission} onChange={setSubmission} />
            <FeedbackSelect exercise_id={exercise?.id} submission_id={submission?.id} feedback={feedback} onChange={setFeedback} />
            <ModuleResponseView response={response} />
            <button
                className="bg-blue-500 text-white rounded-md p-2 mt-4"
                onClick={() => {
                    setLoading(true);
                    sendFeedback(athenaUrl, exercise, submission, feedback)
                        .then(setResponse)
                        .finally(() => setLoading(false));
                }}
                disabled={loading}
            >
                {loading ? "Loading..." : "Send Feedback"}
            </button>
        </div>
    );
}
