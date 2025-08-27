from modules.programming.module_programming_llm.mock.utils.mock_module_config import (
    GradedBasicApproachConfig,
    NonGradedBasicApproachConfig,
    Configuration,
    SplitProblemStatementsWithSolutionByFilePrompt,
    SplitProblemStatementsWithoutSolutionByFilePrompt,
    SplitGradingInstructionsByFilePrompt,
    GradedFeedbackGenerationPrompt,
    NonGradedFeedbackGenerationPrompt,
    FileSummaryPrompt,
)

# Define MockModelConfig locally to avoid importing from mock_env
class MockModelConfig:
    def __init__(self, model_name: str = "mock_model", **model_params):
        self.model_name = model_name
        self.model_params = model_params or {}
    
    def get_model(self):
        from modules.programming.module_programming_llm.mock.utils.mock_llm import MockLanguageModel
        return MockLanguageModel()


def create_mock_graded_config(
    model_config: MockModelConfig,
) -> GradedBasicApproachConfig:
    return GradedBasicApproachConfig(
        max_input_tokens=5000,
        model=model_config,
        max_number_of_files=25,
        split_problem_statement_by_file_prompt=SplitProblemStatementsWithSolutionByFilePrompt(
            system_message="You are a helpful assistant that splits problem statements into file-specific parts.",
            human_message="Split the following problem statement into file-specific parts: {problem_statement}",
            tokens_before_split=250,
        ),
        split_grading_instructions_by_file_prompt=SplitGradingInstructionsByFilePrompt(
            system_message="You are a helpful assistant that splits grading instructions into file-specific parts.",
            human_message="Split the following grading instructions into file-specific parts: {grading_instructions}",
            tokens_before_split=250,
        ),
        generate_suggestions_by_file_prompt=GradedFeedbackGenerationPrompt(
            system_message="You are a helpful assistant that provides graded feedback on code submissions.",
            human_message="Review the following code and provide graded feedback:\n{submission_file}",
            tokens_before_split=250,
        ),
        generate_file_summary_prompt=FileSummaryPrompt(
            system_message="You are a helpful assistant that summarizes code files.",
            human_message="Summarize the following code file:\n{submission_file}",
        ),
    )


def create_mock_non_graded_config(
    model_config: MockModelConfig,
) -> NonGradedBasicApproachConfig:
    return NonGradedBasicApproachConfig(
        max_input_tokens=5000,
        model=model_config,
        max_number_of_files=25,
        split_problem_statement_by_file_prompt=SplitProblemStatementsWithoutSolutionByFilePrompt(
            system_message="You are a helpful assistant that splits problem statements into file-specific parts.",
            human_message="Split the following problem statement into file-specific parts: {problem_statement}",
            tokens_before_split=250,
        ),
        generate_suggestions_by_file_prompt=NonGradedFeedbackGenerationPrompt(
            system_message="You are a helpful assistant that provides non-graded feedback on code submissions.",
            human_message="Review the following code and provide improvement suggestions:\n{submission_file}",
            tokens_before_split=250,
        ),
        generate_file_summary_prompt=FileSummaryPrompt(
            system_message="You are a helpful assistant that summarizes code files.",
            human_message="Summarize the following code file:\n{submission_file}",
        ),
    )


def create_mock_module_config(model_config: MockModelConfig) -> Configuration:
    return Configuration(
        debug=False,
        graded_approach=create_mock_graded_config(model_config),
        non_graded_approach=create_mock_non_graded_config(model_config),
    )


def create_mock_debug_config(model_config: MockModelConfig) -> Configuration:
    config = create_mock_module_config(model_config)
    config.debug = True
    return config


def create_mock_config_with_custom_model(
    model_name: str = "mock_model", **model_params
) -> Configuration:
    model_config = MockModelConfig(model_name=model_name, model_params=model_params)
    return create_mock_module_config(model_config)
