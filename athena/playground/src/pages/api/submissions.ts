import type {NextApiRequest, NextApiResponse} from 'next';
import type Submission from '@/pages/model/submission';

const exampleSubmissions: Submission[] = [
    {
        id: 1,
        exercise_id: 1,
        content: 'http://localhost:3000/api/programming-submissions/1',
        student_id: 1,
        meta: {
            language: 'java',
        }
    },
    {
        id: 2,
        exercise_id: 2,
        content: 'Maximilian',
        student_id: 1,
        meta: {},
    }
];

export default function handler(
    req: NextApiRequest,
    res: NextApiResponse<Submission[]>
) {
    res.status(200).json(exampleSubmissions);
}
