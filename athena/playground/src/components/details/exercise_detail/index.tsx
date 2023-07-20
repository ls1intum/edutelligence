import type { Exercise } from "@/model/exercise";
import type { Mode } from "@/model/mode";

import Disclosure from "@/components/disclosure";

import CommonExerciseDetail from "./common";
import TextExerciseDetail from "./text";
import ProgrammingExerciseDetail from "./programming";

type ExerciseDetailProps = {
  exercise: Exercise;
  mode: Mode;
};

export default function ExerciseDetail({
  exercise,
  mode,
}: ExerciseDetailProps) {
  const specificExerciseDetail = (() => {
    switch (exercise.type) {
      case "text":
        return <TextExerciseDetail exercise={exercise} />;
      case "programming":
        return <ProgrammingExerciseDetail exercise={exercise} mode={mode} />;
      default:
        return null;
    }
  })();

  return (
    <Disclosure
      title="Exercise Detail"
      className={{ root: "mt-2", content: "space-y-1" }}
    >
      <>
        <CommonExerciseDetail exercise={exercise} />
        {specificExerciseDetail}
      </>
    </Disclosure>
  );
}
