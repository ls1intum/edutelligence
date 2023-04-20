import type {NextApiRequest, NextApiResponse} from 'next';
import type Feedback from "@/pages/model/feedback";

const exampleFeedback: Feedback[] = [
    {
        id: 1,
        exercise_id: 1,
        submission_id: 1,
        detail_text: 'Your program does not print "Hello World" to the console.',
        text: 'Your program does not print "Hello World" to the console.',
        credits: -2.0,
        meta: {},
    },
    {
        id: 2,
        exercise_id: 1,
        submission_id: 1,
        detail_text: 'You\'re missing a semicolon at the end of the line.',
        text: 'You\'re missing a semicolon at the end of the line.',
        credits: -2.0,
        meta: {},
    },
    {
        id: 3,
        exercise_id: 2,
        submission_id: 2,
        detail_text: 'You should write your full name.',
        text: 'You should write your full name.',
        credits: -0.5,
        meta: {},
    },
];

export default function handler(
    req: NextApiRequest,
    res: NextApiResponse<Feedback[]>
) {
    res.status(200).json(exampleFeedback);
}
