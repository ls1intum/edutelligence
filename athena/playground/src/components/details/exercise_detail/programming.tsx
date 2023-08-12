import type { ProgrammingExercise } from "@/model/exercise";

import Disclosure from "@/components/disclosure";
import CodeEditor from "@/components/details/editor/code_editor";

export default function ProgrammingExerciseDetail({ exercise }: { exercise: ProgrammingExercise; }) {
  return (
    <>
      <Disclosure title="Template Repository">
        <CodeEditor key={`${exercise.id}/template`} repositoryUrl={exercise.template_repository_url} />
      </Disclosure>
      <Disclosure title="Solution Repository">
        <CodeEditor key={`${exercise.id}/solution`} repositoryUrl={exercise.solution_repository_url} />
      </Disclosure>
      <Disclosure title="Tests Repository">
        <CodeEditor key={`${exercise.id}/tests`} repositoryUrl={exercise.tests_repository_url} />
      </Disclosure>
    </>
  );
}
