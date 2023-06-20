type Feedback = {
  id: number;
  exercise_id: number;
  submission_id: number;
  detail_text?: string;
  reference?: string;
  text?: string;
  credits: number;
  meta: {
    [key: string]: any;
  };
};

export default Feedback;
