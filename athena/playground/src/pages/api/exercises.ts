import type {NextApiRequest, NextApiResponse} from 'next';
import type { Exercise } from '@/model/exercise';

const exampleExercises: Exercise[] = [
    {
        id: 1,
        title: 'Hello World',
        type: 'programming',
        max_points: 10,
        bonus_points: 0,
        problem_statement: 'Write a program that prints "Hello World" to the console.',
        grading_instructions: 'Check if the program prints "Hello World" to the console. 10 points if it does, 0 points otherwise.',
        programming_language: 'java',
        solution_repository_url: 'http://localhost:3000/api/example-solutions/1',
        template_repository_url: 'http://localhost:3000/api/example-template/1',
        tests_repository_url: 'http://localhost:3000/api/example-tests/1',
        meta: {}
    },
    {
        id: 2,
        title: 'What is your name?',
        type: 'text',
        max_points: 10,
        bonus_points: 0,
        grading_instructions: 'Give full points if the student provides their name.',
        problem_statement: 'Write your name in the text field below.',
        example_solution: 'Maximilian',
        meta: {},
    }
];

export default function handler(
    req: NextApiRequest,
    res: NextApiResponse<Exercise[]>
) {
    res.status(200).json(exampleExercises);
}
