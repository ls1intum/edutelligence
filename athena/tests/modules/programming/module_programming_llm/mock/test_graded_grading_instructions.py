from athena.schemas import GradingCriterion, StructuredGradingInstruction

from module_programming_llm.generate_graded_suggestions_by_file import get_grading_instructions_for_file

FILE_PATH = "src/BubbleSort.java"


def _criteria():
    return [
        GradingCriterion(
            id=1,
            title="Bubble Sort",
            structured_grading_instructions=[
                StructuredGradingInstruction(
                    id=7, credits=3.0, grading_scale="Good", feedback="Bubble Sort is implemented correctly."
                ),
                StructuredGradingInstruction(
                    id=8, credits=0.0, grading_scale="Missing", feedback="Bubble Sort is missing."
                ),
            ],
        )
    ]


def test_criteria_reach_the_prompt_when_free_text_instructions_are_empty():
    # Without the criteria and their ids in the prompt the model cannot link a suggestion to a grading instruction.
    file_instructions = get_grading_instructions_for_file(FILE_PATH, None, {}, _criteria())

    assert "grading_instruction_id=7" in file_instructions
    assert "grading_instruction_id=8" in file_instructions
    assert "Bubble Sort is implemented correctly." in file_instructions


def test_short_free_text_instructions_keep_the_criteria():
    file_instructions = get_grading_instructions_for_file(FILE_PATH, "Check the sorting algorithms.", {}, _criteria())

    assert file_instructions.startswith("Check the sorting algorithms.")
    assert "grading_instruction_id=7" in file_instructions


def test_split_free_text_is_used_per_file_and_the_criteria_are_added_unchanged():
    # Splitting rewrites the instructions per file and drops the ids, so the criteria must not go through it.
    split = {FILE_PATH: "Look at the swap in the inner loop.", "src/MergeSort.java": "Look at the merge step."}

    file_instructions = get_grading_instructions_for_file(FILE_PATH, "all free-text instructions", split, _criteria())

    assert file_instructions.startswith("Look at the swap in the inner loop.")
    assert "Look at the merge step." not in file_instructions
    assert "grading_instruction_id=7" in file_instructions
    assert "grading_instruction_id=8" in file_instructions


def test_a_file_without_split_free_text_still_gets_the_criteria():
    split = {"src/MergeSort.java": "Look at the merge step."}

    file_instructions = get_grading_instructions_for_file(FILE_PATH, "all free-text instructions", split, _criteria())

    assert "Look at the merge step." not in file_instructions
    assert "grading_instruction_id=7" in file_instructions


def test_missing_instructions_give_a_placeholder():
    split = {"src/MergeSort.java": "Look at the merge step."}

    assert get_grading_instructions_for_file(FILE_PATH, None, {}, None) == "No grading instructions found."
    assert get_grading_instructions_for_file(FILE_PATH, "   ", {}, []) == "No grading instructions found."
    no_relevant = "No relevant grading instructions found."
    assert get_grading_instructions_for_file(FILE_PATH, "free text", split, None) == no_relevant
