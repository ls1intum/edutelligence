import {useState} from "react";
import { Exercise } from "@/pages/model/exercise";
import ExerciseSelect from "@/pages/components/exercise_select";
import ModuleResponse from "@/pages/model/module_response";
import ModuleResponseView from "@/pages/components/module_response_view";
import Submission from "@/pages/model/submission";

async function requestSubmissionSelection(athenaUrl: string, exercise: Exercise | null): Promise<ModuleResponse | undefined> {
    if (!exercise) {
        alert("Please select an exercise");
        return;
    }
    const submissionsResponse = await fetch(`/api/submissions?${ new URLSearchParams({exercise_id: exercise.id.toString()}) }`);
    const submissions: Submission[] = await submissionsResponse.json();
    try {
        const athenaSubmissionSelectUrl = `${athenaUrl}/select_submission`;
        const response = await fetch(`/api/athena_request?${new URLSearchParams({ url: athenaSubmissionSelectUrl })}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                exercise,
                submission_ids: submissions.map(submission => submission.id),
            })
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
        alert("Submission selection requested successfully!");
        return await response.json();
    } catch (e) {
        console.error(e);
        alert("Failed to request submission selection from Athena: Failed to fetch. Is the URL correct?");
    }
}

export default function SelectSubmission({ athenaUrl }: { athenaUrl: string }) {
    const [exercise, setExercise] = useState<Exercise | null>(null);
    const [loading, setLoading] = useState<boolean>(false);
    const [response, setResponse] = useState<ModuleResponse | undefined>(undefined);

    return (
        <div className="bg-white rounded-md p-4 mt-8">
            <h1 className="text-2xl font-bold mb-4">Request Submission Selection from Athena</h1>
            <p className="text-gray-500 mb-4">
                Request the submission to grade next out out of many submissions from Athena.
                The LMS would usually call this right before a tutor can start grading a submission.
                The matching module for the exercise will receive the request at the function annotated with <code>@submission_selector</code>.
                The playground currently only allows requesting a choice between all submissions of an exercise, but the LMS can also request a choice between a subset of submissions. <br />
                <b>This endpoint will only work properly after the submissions have been sent to Athena before.</b>
            </p>
            <ExerciseSelect exercise={exercise} onChange={setExercise} />
            <ModuleResponseView response={response} />
            <button
                className="bg-blue-500 text-white rounded-md p-2 mt-4"
                onClick={() => {
                    setLoading(true);
                    requestSubmissionSelection(athenaUrl, exercise)
                        .then(setResponse)
                        .finally(() => setLoading(false));
                }}
                disabled={loading}
            >
                {loading ? "Loading..." : "Request Submission Selection"}
            </button>
        </div>
    );
}
