import type { Exercise } from "@/model/exercise";

import Markdown from "@/components/markdown";
import Disclosure from "@/components/disclosure";
import StructuredGradingInstructionDetail from "./structured_grading_instruction_detail";

export default function CommonExerciseDetail({
  exercise,
  openedInitially,
}: {
  exercise: Exercise;
  openedInitially?: boolean;
}) {
  const hasAtLeastOneSGI =
    exercise.grading_criteria &&
    exercise.grading_criteria.some(
      (criterion) => criterion.structured_grading_instructions.length > 0
    );

  return (
    <>
      <div className="text-gray-500 font-medium">
        {exercise.max_points} Points and {exercise.bonus_points} Bonus Points
      </div>
      {/* Problem Statement */}
      <Disclosure title="Problem Statement" openedInitially={openedInitially}>
        {exercise.problem_statement ? (
          <Markdown
            content={exercise.problem_statement ?? ""}
            enablePlainTextSwitcher
          />
        ) : (
          <span className="text-gray-500">No problem statement available</span>
        )}
      </Disclosure>

      {/* Grading Instructions */}
      <Disclosure title="Grading Instructions">
        <>
          <div className="flex flex-col gap-4">
            {exercise.grading_instructions && (
              <Markdown
                content={exercise.grading_instructions || ""}
                enablePlainTextSwitcher
              />
            )}
            {exercise.grading_criteria &&
              exercise.grading_criteria.map((criterion) => (
                <div key={criterion.id} className="flex flex-col gap-1">
                  <span className="flex gap-2 text-gray-500 font-medium">
                    {criterion.title ? (
                      criterion.title
                    ) : (
                      <i>Missing criterion title</i>
                    )}
                    <span className="text-xs text-orange-800 rounded-full px-2 py-0.5 bg-orange-100">
                      Grading&nbsp;Criterion&nbsp;{criterion.id}
                    </span>
                  </span>
                  {criterion.structured_grading_instructions.map(
                    (instruction) => (
                      <StructuredGradingInstructionDetail
                        key={instruction.id}
                        criterionTitle={criterion.title}
                        instruction={instruction}
                      />
                    )
                  )}
                </div>
              ))}
            {!exercise.grading_instructions && !hasAtLeastOneSGI && (
              <span className="text-gray-500">
                No grading instructions available
              </span>
            )}
          </div>
        </>
      </Disclosure>
    </>
  );
}
