type Submission = {
    id: number;
    exercise_id: number;
    content: string;
    student_id: number;
    meta: {
        [key: string]: any;
    };
};

export default Submission;