import type { ProgrammingExercise } from "@/model/exercise";

import Disclosure from "@/components/disclosure";
import CodeView from "@/components/details/code_view";

export default function ProgrammingExerciseDetail({ exercise }: { exercise: ProgrammingExercise; }) {
  return (
    <>
      <Disclosure title="Template Repository">
        <CodeView repository_url={exercise.template_repository_url} />
      </Disclosure>
      <Disclosure title="Solution Repository">
        <CodeView repository_url={exercise.solution_repository_url} />
      </Disclosure>
      <Disclosure title="Tests Repository">
        <CodeView repository_url={exercise.tests_repository_url} />
      </Disclosure>
    </>
  );
}
