import type {NextApiRequest, NextApiResponse} from 'next';
import type { Exercise } from '@/model/exercise';
import {getExampleExercises} from "@/pages/api/get_examples";

export default function handler(
    req: NextApiRequest,
    res: NextApiResponse<Exercise[]>
) {
    res.status(200).json(getExampleExercises());
}
