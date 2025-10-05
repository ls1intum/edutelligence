from typing import Any

from langchain.agents.agent import RunnableMultiActionAgent
from langchain_core.agents import AgentAction, AgentFinish


class ImprovedLangchainAgent(RunnableMultiActionAgent):
    """
    An improved version of LangChain's RunnableMultiActionAgent with better early stopping handling.
    Specifically, it enables the "generate" early stopping method, which allows the agent to
    generate a final response instead of just forcing a stop.
    """

    def return_stopped_response(
        self,
        early_stopping_method: str,
        intermediate_steps: list[tuple[AgentAction, str]],
        **kwargs: Any,
    ) -> AgentFinish:
        if early_stopping_method == "force":
            # `force` just returns a constant string
            return AgentFinish(
                {"output": "Agent stopped due to iteration limit or time limit."},
                "",
            )
        if early_stopping_method == "generate":
            # Add a message to the LLM to generate a final response
            new_intermediate_steps = intermediate_steps + [
                (
                    AgentAction(
                        tool="Final Answer?",
                        tool_input="You must now generate a final answer based on the previous steps. "
                        "Output the final JSON. YOU CAN'T CALL ANY MORE TOOLS! THIS IS CRITICAL!",
                        log="You must now generate a final answer based on the previous steps. "
                        "Output the final JSON. YOU CAN'T CALL ANY MORE TOOLS! THIS IS CRITICAL!",
                    ),
                    "You must now generate a final answer based on the previous steps. "
                    "Output the final JSON. YOU CAN'T CALL ANY MORE TOOLS! THIS IS CRITICAL!",
                )
            ]
            response = self.plan(new_intermediate_steps, **kwargs)
            if isinstance(response, AgentFinish):
                return response
            else:
                raise ValueError(f"Got unexpected response {response} from LLM")
        msg = (
            "early_stopping_method should be one of `force` or `generate`, "
            f"got {early_stopping_method}"
        )
        raise ValueError(msg)
