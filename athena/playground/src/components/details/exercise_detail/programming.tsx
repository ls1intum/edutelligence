import type { ProgrammingExercise } from "@/model/exercise";

import Disclosure from "@/components/disclosure";
import CodeEditor from "@/components/details/editor/code_editor";

export default function ProgrammingExerciseDetail({ exercise, openedInitially }: { exercise: ProgrammingExercise; openedInitially?: boolean; }) {
  return (
    <>
      <Disclosure title="Template Repository" openedInitially={openedInitially} noContentIndent>
        <CodeEditor key={`${exercise.id}/template`} repository_url={exercise.template_repository_url} />
      </Disclosure>
      <Disclosure title="Solution Repository" openedInitially={openedInitially} noContentIndent>
        <CodeEditor key={`${exercise.id}/solution`} repository_url={exercise.solution_repository_url} />
      </Disclosure>
      <Disclosure title="Tests Repository" openedInitially={openedInitially} noContentIndent>
        <CodeEditor key={`${exercise.id}/tests`} repository_url={exercise.tests_repository_url} />
      </Disclosure>
    </>
  );
}
