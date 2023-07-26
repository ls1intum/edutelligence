import type { ProgrammingExercise } from "@/model/exercise";

import Disclosure from "@/components/disclosure";
import CodeEditor from "@/components/details/editor/code_editor";

export default function ProgrammingExerciseDetail({ exercise }: { exercise: ProgrammingExercise; }) {
  return (
    <>
      <Disclosure title="Template Repository">
        <CodeEditor repository_url={exercise.template_repository_url} />
      </Disclosure>
      <Disclosure title="Solution Repository">
        <CodeEditor repository_url={exercise.solution_repository_url} />
      </Disclosure>
      <Disclosure title="Tests Repository">
        <CodeEditor repository_url={exercise.tests_repository_url} />
      </Disclosure>
    </>
  );
}
