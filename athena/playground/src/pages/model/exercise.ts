type Exercise = {
    id: number;
    title: string;
    type: string;
    max_points: number;
    problem_statement: string;
    example_solution: string;
    student_id: number;
    meta: {
        [key: string]: any;
    };
};

export default Exercise;