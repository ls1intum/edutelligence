import type { ProgrammingExercise } from "@/model/exercise";

import Disclosure from "@/components/disclosure";
import CodeEditor from "@/components/details/editor/code_editor";

export default function ProgrammingExerciseDetail({ exercise }: { exercise: ProgrammingExercise; }) {
  return (
    <>
      <Disclosure title="Template Repository">
        <CodeEditor key={`${exercise.id}/template`} repository_url={exercise.template_repository_url} />
      </Disclosure>
      <Disclosure title="Solution Repository">
        <CodeEditor key={`${exercise.id}/solution`} repository_url={exercise.solution_repository_url} />
      </Disclosure>
      <Disclosure title="Tests Repository">
        <CodeEditor key={`${exercise.id}/tests`} repository_url={exercise.tests_repository_url} />
      </Disclosure>
    </>
  );
}
