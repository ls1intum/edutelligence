import type {NextApiRequest, NextApiResponse} from 'next';
import type Submission from '@/pages/model/submission';

const exampleSubmissions: Submission[] = [
    {
        id: 1,
        exercise_id: 1,
        content: 'http://localhost:3000/api/programming-submissions/1.zip',
        student_id: 1,
        meta: {}
    },
    {
        id: 2,
        exercise_id: 1,
        content: 'http://localhost:3000/api/programming-submissions/2.zip',
        student_id: 2,
        meta: {}
    },
    {
        id: 3,
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
    let exerciseId = req.query.exercise_id;
    if (exerciseId) {
        res.status(200).json(exampleSubmissions.filter(submission => submission.exercise_id === parseInt(exerciseId as string)));
        return;
    }
    res.status(200).json(exampleSubmissions);
}
