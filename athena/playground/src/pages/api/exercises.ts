import type {NextApiRequest, NextApiResponse} from 'next';
import type Exercise from '@/pages/model/exercise';

const exampleExercises: Exercise[] = [
    {
        id: 1,
        title: 'Hello World',
        type: 'programming',
        max_points: 10,
        problem_statement: 'Write a program that prints "Hello World" to the console.',
        example_solution: 'http://localhost:3000/api/example-solutions/1',
        student_id: 1,
        meta: {
            language: 'java',
        }
    },
    {
        id: 2,
        title: 'What is your name?',
        type: 'text',
        max_points: 10,
        problem_statement: 'Write your name in the text field below.',
        example_solution: 'Maximilian',
        student_id: 1,
        meta: {},
    }
];

export default function handler(
    req: NextApiRequest,
    res: NextApiResponse<Exercise[]>
) {
    res.status(200).json(exampleExercises);
}
