from typing import List
from athena import emit_meta
from athena.text import Exercise, Submission, Feedback
from athena.logger import logger
from llm_core.llm_core.ollama_agent import MultiAgentExecutor
from module_text_llm.approach_config import ApproachConfig

# Placeholder for generate suggestions logic.
def generate_suggestions(exercise: Exercise, submission: Submission, config: ApproachConfig, debug: bool, is_graded: bool):
    def retrieve_previous_feedback_for_chunk(chunks: List[str]) -> List[Feedback]:
        """Retrieve previous feedback for a given list of chunks.

        Args:
            chunks (List[str]): A list of chunk identifiers for which previous feedback is being retrieved.

        Returns:
            List[Feedback]: A list of `Feedback` objects corresponding to the provided chunks.
        """
        return ["Example feedback" , "More example feedback"]
    tools = [retrieve_previous_feedback_for_chunk] #icl
    agent_executor = MultiAgentExecutor(
        model = "llama3.3:latest",
        tools = tools,
        exercise = exercise,
        submission = submission,
        )
    agent_executor.invoke_deliberation(rounds = 3, conensus_mechanism = "unanimity")
    return None
    