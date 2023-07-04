type Feedback = {
  id: number;
  exercise_id: number;
  submission_id: number;
  text?: string;
  detail_text?: string;
  index_start: number;
  index_end: number;
  reference?: string;
  credits: number;
  meta: {
    [key: string]: any;
  };
};

export default Feedback;
