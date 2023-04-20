import {Inter} from 'next/font/google';
import ExerciseSelect from "@/pages/components/exercise_select";
import SubmissionSelect from "@/pages/components/submission_select";
import FeedbackSelect from "@/pages/components/feedback_select";
import Exercise from "@/pages/model/exercise";
import Submission from "@/pages/model/submission";
import Feedback from "@/pages/model/feedback";
import {useState} from "react";

const inter = Inter({subsets: ['latin']});

export default function Home() {
    const [exercise, setExercise] = useState<Exercise | null>(null);
    const [submission, setSubmission] = useState<Submission | null>(null);
    const [feedback, setFeedback] = useState<Feedback | null>(null);

    return (
        <main className="flex min-h-screen flex-col p-24">
            <h1 className="text-6xl font-bold">Playground</h1>
            <ExerciseSelect exercise={exercise} onChange={setExercise}/>
            <SubmissionSelect exercise_id={exercise?.id} submission={submission} onChange={setSubmission}/>
            <FeedbackSelect exercise_id={exercise?.id} submission_id={submission?.id} feedback={feedback} onChange={setFeedback}/>
        </main>
    );
}
