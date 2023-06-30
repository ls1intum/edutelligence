import { TextExercise } from "@/model/exercise";
import Markdown from "@/components/markdown";
import Disclosure from "@/components/disclosure";

type TextExerciseDetailProps = {
  exercise: TextExercise;
};

export default function TextExerciseDetail({
  exercise,
}: TextExerciseDetailProps) {
  return (
    <Disclosure title="Example Solution">
      {exercise.example_solution.length > 0 ? (
        <Markdown content={exercise.example_solution} enablePlainTextSwitcher />
      ) : (
        <span className="text-gray-500">No example solution available</span>
      )}
    </Disclosure>
  );
}
