import {useState} from "react";
import { Submission } from "@/model/submission";
import { Exercise } from "@/model/exercise";
import ExerciseSelect from "@/components/exercise_select";
import SubmissionSelect from "@/components/submission_select";
import FeedbackSelect from "@/components/feedback_select";
import Feedback from "@/model/feedback";
import ModuleResponse from "@/model/module_response";
import ModuleResponseView from "@/components/module_response_view";
import {ModuleMeta} from "@/model/health_response";
import baseUrl from "@/helpers/base_url";

async function sendFeedback(
    athenaUrl: string,
    athenaSecret: string,
    module: ModuleMeta,
    exercise: Exercise | null,
    submission: Submission | null,
    feedback: Feedback | null,
    alertAfterSuccess: boolean = true
): Promise<ModuleResponse | undefined> {
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
        const athenaFeedbackUrl = `${athenaUrl}/modules/${module.type}/${module.name}/feedback`;
        const response = await fetch(`${baseUrl}/api/athena_request?${new URLSearchParams({ url: athenaFeedbackUrl })}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-API-Secret': athenaSecret
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
        if (alertAfterSuccess) {
            alert("Feedback sent successfully!");
        }
        return await response.json();
    } catch (e) {
        console.error(e);
        alert("Failed to send feedback to Athena: Failed to fetch. Is the URL correct?");
    }
}

async function sendAllExerciseFeedbacks(
    athenaUrl: string,
    athenaSecret: string,
    module: ModuleMeta,
    exercise?: Exercise
): Promise<ModuleResponse[] | undefined> {
    if (!exercise) {
        alert("Please select an exercise");
        return;
    }
    // fetch submissions for exercise from /api/submissions
    const submissionResponse = await fetch(`${baseUrl}/api/submissions?${new URLSearchParams({ exercise_id: exercise.id.toString() })}`);
    if (submissionResponse.status !== 200) {
        console.error(submissionResponse);
        alert(`Failed to fetch submissions for exercise ${exercise.id}`);
        return;
    }
    const submissions: Submission[] = await submissionResponse.json();
    // fetch feedbacks for exercise from /api/feedbacks
    const feedbackResponse = await fetch(`${baseUrl}/api/feedbacks?${new URLSearchParams({ exercise_id: exercise.id.toString() })}`);
    if (feedbackResponse.status !== 200) {
        console.error(feedbackResponse);
        alert(`Failed to fetch feedbacks for exercise ${exercise.id}`);
        return;
    }
    const feedbacks: Feedback[] = await feedbackResponse.json();
    if (feedbacks.length === 0) {
        alert("No feedbacks found for exercise");
        return;
    }
    const responses: ModuleResponse[] = [];
    for (const feedback of feedbacks) {
        const submission = submissions.find(s => s.id === feedback.submission_id);
        const response = await sendFeedback(athenaUrl, athenaSecret, module, exercise, submission!, feedback, false);
        if (response) {
            responses.push(response);
        } else {
            // something went wrong, abort
            return;
        }
    }
    alert(`${feedbacks.length} feedbacks sent`);
    return responses;
}

export default function SendFeedback(
    { athenaUrl, athenaSecret, module }: { athenaUrl: string, athenaSecret: string, module: ModuleMeta }
) {
    const [exercise, setExercise] = useState<Exercise | null>(null);
    const [isAllSubmissions, setIsAllSubmissions] = useState<boolean>(true);
    const [submission, setSubmission] = useState<Submission | null>(null);
    const [feedback, setFeedback] = useState<Feedback | null>(null);
    const [loading, setLoading] = useState<boolean>(false);
    const [responses, setResponses] = useState<ModuleResponse[] | undefined>(undefined);

    return (
        <div className="bg-white rounded-md p-4 mt-8">
            <h1 className="text-2xl font-bold mb-4">Send Feedback to Athena</h1>
            <p className="text-gray-500 mb-4">
                Send a single given feedback to Athena, or all feedback for the whole exercise.
                This usually happens when someone gives feedback on the submission in the LMS.
                The matching module for the exercise will receive the feedback at the function annotated with <code>@feedback_consumer</code>.
            </p>
            <ExerciseSelect exerciseType={module.type} exercise={exercise} onChange={setExercise} />
            <SubmissionSelect
                exercise_id={exercise?.id}
                submission={submission} onChange={setSubmission}
                isAllSubmissions={isAllSubmissions} setIsAllSubmissions={setIsAllSubmissions}
            />
            {
                isAllSubmissions &&
                <div className="bg-yellow-200 rounded-md p-2 mb-4 mt-2">
                    <p className="text-yellow-800">
                        You are about to send feedback for all submissions of this exercise.
                        This will send a request for each feedback of each submission.
                    </p>
                </div>
            }
            {
                !isAllSubmissions &&
                <FeedbackSelect exercise_id={exercise?.id} submission_id={submission?.id} feedback={feedback} onChange={setFeedback} />
            }
            {
                responses?.map((response, i) => <ModuleResponseView key={i} response={response} />)
            }
            <button
                className="bg-blue-500 text-white rounded-md p-2 mt-4"
                onClick={() => {
                    setLoading(true);
                    if (isAllSubmissions) {
                        sendAllExerciseFeedbacks(athenaUrl, athenaSecret, module, exercise!)
                            .then(setResponses)
                            .finally(() => setLoading(false));
                        return;
                    }
                    sendFeedback(athenaUrl, athenaSecret, module, exercise, submission, feedback)
                        .then(resp => setResponses(resp ? [resp] : undefined))
                        .finally(() => setLoading(false));
                }}
                disabled={loading}
            >
                {loading ? "Loading..." : "Send Feedback"}
            </button>
        </div>
    );
}
