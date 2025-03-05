import { Submission } from "@/model/submission";

export type ExerciseType = "text" | "programming" | "modeling";

export type StructuredGradingInstruction = {
  id: number;
  credits: number;
  feedback: string;
  usage_count: number;
  grading_scale: string;
  instruction_description: string;
};

export type GradingCriteria = {
  id: number;
  title: string;
  structured_grading_instructions: StructuredGradingInstruction[]
};

type ExerciseBase = {
  id: number;
  course_id: number;
  title: string;
  type: ExerciseType;
  max_points: number;
  bonus_points: number;
  grading_instructions?: string;
  grading_criteria?: GradingCriteria[];
  problem_statement?: string;
  submissions?: Submission[]; // Playground only
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
  solution_repository_uri: string;
  template_repository_uri: string;
  tests_repository_uri: string;
};

export type ModelingExercise = ExerciseBase & {
  type: "modeling";
  example_solution?: string;
};

export type Exercise = TextExercise | ProgrammingExercise | ModelingExercise;
