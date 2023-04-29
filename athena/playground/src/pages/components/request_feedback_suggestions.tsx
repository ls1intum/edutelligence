import {useState} from "react";
import Submission from "@/pages/model/submission";
import { Exercise } from "@/pages/model/exercise";
import ExerciseSelect from "@/pages/components/exercise_select";
import SubmissionSelect from "@/pages/components/submission_select";
import ModuleResponse from "@/pages/model/module_response";
import ModuleResponseView from "@/pages/components/module_response_view";

async function requestFeedbackSuggestions(athenaUrl: string, exercise: Exercise | null, submission: Submission | null): Promise<ModuleResponse | undefined> {
    if (!exercise) {
        alert("Please select an exercise");
        return;
    }
    if (!submission) {
        alert("Please select a submission");
        return;
    }
    try {
        const athenaFeedbackUrl = `${athenaUrl}/feedback_suggestions`;
        const response = await fetch(`/api/athena_request?${new URLSearchParams({ url: athenaFeedbackUrl })}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ exercise, submission })
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
        alert("Feedback suggestions requested successfully!");
        return await response.json();
    } catch (e) {
        console.error(e);
        alert("Failed to request feedback suggestions from Athena: Failed to fetch. Is the URL correct?");
    }
}

export default function RequestFeedbackSuggestions({ athenaUrl }: { athenaUrl: string }) {
    const [exercise, setExercise] = useState<Exercise | null>(null);
    const [submission, setSubmission] = useState<Submission | null>(null);
    const [loading, setLoading] = useState<boolean>(false);
    const [response, setResponse] = useState<ModuleResponse | undefined>(undefined);

    return (
        <div className="bg-white rounded-md p-4 mt-8">
            <h1 className="text-2xl font-bold mb-4">Request Feedback Suggestions from Athena</h1>
            <p className="text-gray-500 mb-4">
                Request a list of feedback suggestions from Athena for the selected submission.
                The LMS would usually call this when a tutor starts grading a submission.
                The matching module for the exercise will receive the request at the function annotated with <code>@feedback_provider</code>.
            </p>
            <ExerciseSelect exercise={exercise} onChange={setExercise} />
            <SubmissionSelect exercise_id={exercise?.id} submission={submission} onChange={setSubmission} />
            <ModuleResponseView response={response} />
            <button
                className="bg-blue-500 text-white rounded-md p-2 mt-4"
                onClick={() => {
                    setLoading(true);
                    requestFeedbackSuggestions(athenaUrl, exercise, submission)
                        .then(setResponse)
                        .finally(() => setLoading(false));
                }}
                disabled={loading}
            >
                {loading ? "Loading..." : "Request Feedback Suggestions"}
            </button>
        </div>
    );
}
