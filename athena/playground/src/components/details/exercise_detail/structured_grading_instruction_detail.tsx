import type { StructuredGradingInstruction } from "@/model/exercise";

import { twMerge } from "tailwind-merge";

type StructuredGradingInstructionDetailProps = {
  criterionTitle?: string;
  instruction: StructuredGradingInstruction;
};

export default function StructuredGradingInstructionDetail({
  criterionTitle,
  instruction,
}: StructuredGradingInstructionDetailProps) {
  return (
    <div
      className={twMerge(
        "my-1 mx-1 border border-gray-300 rounded-lg text-sm max-w-3xl",
        [
          "hover:outline outline-2 hover:shadow transition-all duration-200",
          instruction.credits < 0
            ? "outline-red-300/50"
            : instruction.credits > 0
            ? "outline-green-300/50"
            : "outline-yellow-300/50",
        ]
      )}
    >
      <div className="flex items-center gap-1 justify-start px-4 py-2 border-b border-gray-300 text-xs text-gray-600">
        <b>
          {instruction.grading_scale ? (
            instruction.grading_scale
          ) : (
            <i>Missing grading scale</i>
          )}
        </b>
        <span>can be used</span>
        <b>
          {instruction.usage_count === 0
            ? " arbitrarily often"
            : ` ${instruction.usage_count} times`}
        </b>
      </div>
      <div className="flex justify-start items-start space-x-2 px-4 py-2">
        <div
          className={twMerge(
            "font-medium rounded px-2.5 py-0.5 mt-2",
            instruction.credits < 0
              ? "bg-red-100 text-red-800"
              : instruction.credits > 0
              ? "bg-green-100 text-green-800"
              : "bg-yellow-100 text-yellow-800"
          )}
        >
          {instruction.credits}&nbsp;P
        </div>
        <div className="w-full">
          <div className="flex items-center justify-between space-x-1">
            <span className="font-semibold">
              {criterionTitle ? criterionTitle : <i>Missing title</i>}
            </span>
            <div className="flex gap-1">
              <span className="text-xs text-orange-800 rounded-full px-2 py-0.5 bg-orange-100">
                Grading&nbsp;Instruction&nbsp;{instruction.id}
              </span>
            </div>
          </div>
          <div>
            {instruction.feedback ? (
              <span className="whitespace-pre-wrap">
                {instruction.feedback}
              </span>
            ) : (
              <i>Missing description</i>
            )}
          </div>
        </div>
      </div>
      <div className="items-center justify-start px-4 py-2 border-t border-gray-300 text-xs text-gray-600">
        <b>Usage&nbsp;description:</b> {instruction.instruction_description ? instruction.instruction_description : <i>Missing description</i>}
      </div>
    </div>
  );
}
