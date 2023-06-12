import type {NextApiRequest, NextApiResponse} from 'next';
import type {Submission} from '@/model/submission';
import {getExampleSubmissions} from "@/pages/api/get_examples";
import getOriginFromRequest from '@/helpers/origin_from_req';


export default function handler(
    req: NextApiRequest,
    res: NextApiResponse<Submission[]>
) {
    let exerciseId = req.query.exercise_id;
    const exampleSubmissions = getExampleSubmissions(exerciseId ? parseInt(exerciseId as string) : undefined, getOriginFromRequest(req));
    res.status(200).json(exampleSubmissions);
}
