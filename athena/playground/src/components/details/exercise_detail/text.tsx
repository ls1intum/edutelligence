import type { TextExercise } from "@/model/exercise";

import Disclosure from "@/components/disclosure";
import FileEditor from "@/components/details/editor/file_editor";

export default function TextExerciseDetail({ exercise }: { exercise: TextExercise }) {
  return (
    <Disclosure title="Example Solution" noContentIndent>
      {exercise.example_solution.length > 0 ? (
        <FileEditor content={exercise.example_solution} />
      ) : (
        <span className="text-gray-500">No example solution available</span>
      )}
    </Disclosure>
  );
}
