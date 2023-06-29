import { Exercise } from "@/model/exercise";
import Markdown from "@/components/markdown";
import Disclosure from "@/components/disclosure";

type CommonExerciseDetailProps = {
  exercise: Exercise;
};

export default function CommonExerciseDetail({ exercise }: CommonExerciseDetailProps) {
  return (
    <>
      {/* Problem Statement */}
      <Disclosure title="Problem Statement">
        {exercise.problem_statement.length > 0 ? (
          <Markdown
            content={exercise.problem_statement}
            enablePlainTextSwitcher
          />
        ) : (
          <span className="text-gray-500">No problem statement available</span>
        )}
      </Disclosure>

      {/* Grading Instructions */}
      <Disclosure title="Grading Instructions">
        {exercise.grading_instructions.length > 0 ? (
          <Markdown
            content={exercise.grading_instructions}
            enablePlainTextSwitcher
          />
        ) : (
          <span className="text-gray-500">
            No grading instructions available
          </span>
        )}
      </Disclosure>
    </>
  );
}
