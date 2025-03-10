import type { ProgrammingExercise } from "@/model/exercise";

import Disclosure from "@/components/disclosure";
import CodeEditor from "@/components/details/editor/code_editor";

export default function ProgrammingExerciseDetail({ exercise, openedInitially }: { exercise: ProgrammingExercise; openedInitially?: boolean; }) {
  return (
    <>
      <Disclosure title="Solution Repository" openedInitially={openedInitially} noContentIndent>
        <CodeEditor key={`${exercise.id}/solution`} repositoryUrl={exercise.solution_repository_uri} />
      </Disclosure>
      <Disclosure title="Template Repository" openedInitially={openedInitially} noContentIndent>
        <CodeEditor key={`${exercise.id}/template`} repositoryUrl={exercise.template_repository_uri} />
      </Disclosure>
      <Disclosure title="Tests Repository" openedInitially={openedInitially} noContentIndent>
        <CodeEditor key={`${exercise.id}/tests`} repositoryUrl={exercise.tests_repository_uri} />
      </Disclosure>
    </>
  );
}
