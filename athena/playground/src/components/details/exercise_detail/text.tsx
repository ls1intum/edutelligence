import type { TextExercise } from "@/model/exercise";

import Disclosure from "@/components/disclosure";
import FileEditor from "@/components/details/editor/file_editor";

export default function TextExerciseDetail({
  exercise,
}: {
  exercise: TextExercise;
}) {
  return (
    <Disclosure title="Example Solution" noContentIndent>
      {exercise.example_solution.length > 0 ? (
        <div className="border border-gray-100 rounded-lg overflow-hidden">
          <FileEditor
            key={`${exercise.id}/solution`}
            identifier={`exercise-${exercise.id}/solution`}
            content={exercise.example_solution}
            autoHeight
          />
        </div>
      ) : (
        <span className="text-gray-500">No example solution available</span>
      )}
    </Disclosure>
  );
}
