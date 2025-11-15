import type { Exercise } from "@/model/exercise";

import Disclosure from "@/components/disclosure";

import CommonExerciseDetail from "./common";
import TextExerciseDetail from "./text";
import ProgrammingExerciseDetail from "./programming";
import ModelingExerciseDetail from "./modeling";

type ExerciseDetailProps = {
  exercise: Exercise;
  hideDisclosure?: boolean;
  openedInitially?: boolean;
};

export default function ExerciseDetail({
  exercise,
  hideDisclosure,
  openedInitially,
}: ExerciseDetailProps) {
  const specificExerciseDetail = (() => {
    switch (exercise.type) {
      case "text":
        return <TextExerciseDetail exercise={exercise} openedInitially={openedInitially} />;
      case "programming":
        return <ProgrammingExerciseDetail exercise={exercise} openedInitially={openedInitially} />;
      case "modeling":
        return <ModelingExerciseDetail exercise={exercise} openedInitially={openedInitially} />;
      default:
        return null;
    }
  })();

  return hideDisclosure ? (
    <div className="mt-2 space-y-1 w-full lg:w-[60vw] max-h-[50vh] overflow-y-auto overflow-x-hidden flex flex-col">
      <CommonExerciseDetail exercise={exercise} openedInitially={openedInitially} />
      {specificExerciseDetail}
    </div>
  ) : (
    <Disclosure
      title="Exercise Detail"
      className={{ root: "mt-2", content: "space-y-1" }}
      openedInitially={openedInitially}
    >
      <>
        <CommonExerciseDetail exercise={exercise} />
        {specificExerciseDetail}
      </>
    </Disclosure>
  );
}
