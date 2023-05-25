import type {NextApiRequest, NextApiResponse} from 'next';
import type Feedback from "@/model/feedback";
import {getExampleFeedbacks} from "@/pages/api/get_examples";


export default function handler(
    req: NextApiRequest,
    res: NextApiResponse<Feedback[]>
) {
    let exerciseId: number | undefined = undefined;
    if (req.query.exercise_id) {
        exerciseId = parseInt(req.query.exercise_id as string);
    }
    res.status(200).json(getExampleFeedbacks(exerciseId));
}
