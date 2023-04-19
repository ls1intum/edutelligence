type Feedback = {
    id: number;
    exercise_id: number;
    submission_id: number;
    detail_text: string;
    text: string;
    credits: number;
    meta: {
        [key: string]: any;
    };
};

export default Feedback;