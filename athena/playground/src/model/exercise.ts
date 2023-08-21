export type ExerciseType = "text" | "programming";

type ExerciseBase = {
  id: number;
  course_id: number;
  title: string;
  type: ExerciseType;
  max_points: number;
  bonus_points: number;
  grading_instructions?: string;
  problem_statement: string;
  meta: {
    [key: string]: any;
  };
};

export type TextExercise = ExerciseBase & {
  type: "text";
  example_solution?: string;
};

export type ProgrammingExercise = ExerciseBase & {
  type: "programming";
  programming_language: string;
  solution_repository_url: string;
  template_repository_url: string;
  tests_repository_url: string;
};

export type Exercise = TextExercise | ProgrammingExercise;
