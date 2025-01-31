import logging
import operator
import random
from typing import Annotated, List, Literal, Optional, Union

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_core.runnables import Runnable
from langsmith import traceable
from langgraph.graph import StateGraph, START, END
from pydantic import BaseModel, Field
from typing_extensions import TypedDict
from langchain_core.runnables import RunnableConfig
from langgraph.graph.message import add_messages

from app.common.PipelineEnum import PipelineEnum
from app.domain import InconsistencyCheckPipelineExecutionDTO
from app.llm import CapabilityRequestHandler, RequirementList, CompletionArguments
from app.llm.langchain.iris_langchain_chat_model import IrisLangchainChatModel
from app.pipeline import Pipeline
from app.web.status.status_update import InconsistencyCheckCallback
from app.pipeline.prompts.inconsistency_check_prompts import solver_prompt, scorer_prompt, aggregator_prompt

logger = logging.getLogger(__name__)


IssueLocation = Literal["problem_statement", "template_file", "solution_file", "uncertain"]


class ConsistencyIssue(BaseModel):
    """The consistency issue found in the programming exercise."""

    location: IssueLocation = Field(
        description="The location of the consistency issue in the programming exercise."
    )
    
    title: str = Field(
        description="The title of the consistency issue found in the programming exercise."
    )

    description: str = Field(
        description="The description of the consistency issue found in the programming exercise."
    )
    
    suggestion: str = Field(
        description="The suggestion to fix the consistency issue found in the programming exercise."
    )


class GuessConsistencyIssues(BaseModel):
    """Submit multiple consistency issues found in the programming exercise as guesses."""
    
    reasoning: str = Field(
        description="The reasoning behind the submitted guesses. Explain how you arrived at these consistency issues."
    )
    
    issues: List[ConsistencyIssue] = Field(
        description="The list of consistency issues found in the programming exercise."
    )    


class ScoredConsistencyIssue(BaseModel):
    """The scored consistency issue found in the programming exercise."""

    candidate: ConsistencyIssue = Field(
        description="The candidate consistency issue under review."
    )

    score_reasoning: str = Field(
        description="The reasoning behind the score given to the consistency issue."
    )

    score: float = Field(
        description="The score given to the consistency issue. The score should be between 0.00 and 1.00"
    )


Candidate = GuessConsistencyIssues

class ScoredCandidate(BaseModel):
    scored_issues: List[ScoredConsistencyIssue] = Field(
        description="The list of scored consistency issues found in the programming exercise."
    )
    
    final_score_reasoning: str = Field(
        description="The reasoning behind the final score given to the consistency issues."
    )
    
    final_score: float = Field(
        description="The final score given to the consistency issues. The score should be between 0.00 and 1.00"
    )


def update_candidates(
    existing: Optional[list] = None,
    updates: Optional[Union[list, Literal["clear"]]] = None,
) -> list:
    if existing is None:
        existing = []
    if updates is None:
        return existing
    if updates == "clear":
        return []
    # Concatenate the lists
    return existing + updates


class FileConsistencyIssuesState(TypedDict):
    file_path: str
    problem_statement: str
    template_file_content: str
    solution_file_content: str
    
    candidates: Annotated[List[Candidate], update_candidates]
    scored_candidates: Annotated[List[ScoredCandidate], update_candidates]
    depth: Annotated[int, operator.add]


class Configuration(TypedDict, total=False):
    max_depth: int
    threshold: float
    k: int
    beam_size: int


def _ensure_configurable(config: RunnableConfig) -> Configuration:
    """Get params that configure the search algorithm."""
    configurable = config.get("configurable", {})
    return {
        **configurable,
        "max_depth": configurable.get("max_depth", 5),
        "threshold": config.get("threshold", 0.9),
        "k": configurable.get("k", 5),
        "beam_size": configurable.get("beam_size", 3),
    }


class InconsistencyCheckPipeline(Pipeline):
    solver: Runnable
    scorer: Runnable
    aggregator: Runnable
    
    llm: IrisLangchainChatModel
    callback: InconsistencyCheckCallback

    def __init__(self, callback: Optional[InconsistencyCheckCallback] = None):
        super().__init__(implementation_id="inconsistency_check_pipeline")
        completion_args = CompletionArguments(temperature=0, max_tokens=2000)
        self.llm = IrisLangchainChatModel(
            request_handler=CapabilityRequestHandler(
                requirements=RequirementList(
                    gpt_version_equivalent=4.5,
                    context_length=16385,
                )
            ),
            completion_args=completion_args,
        )
        self.prompt = PromptTemplate.from_template(basic_prompt)
        self.pipeline = self.prompt | self.llm | StrOutputParser()
        self.callback = callback
        self.tokens = []

        # Guess consistency issues
        solver_prompt_template = PromptTemplate.from_template(solver_prompt)
        solver_bound_llm = self.llm.with_structured_output(GuessConsistencyIssues)
        self.solver = solver_prompt_template | solver_bound_llm
        
        # Score consistency issues
        scorer_prompt_template = PromptTemplate.from_template(scorer_prompt)
        scorer_bound_llm = self.llm.with_structured_output(ScoredConsistencyIssues)
        self.scorer = scorer_prompt_template | scorer_bound_llm
        
        # Score and merge consistency issues
        aggregator_prompt_template = PromptTemplate.from_template(aggregator_prompt)
        aggregator_bound_llm = self.llm.with_structured_output(ScoredConsistencyIssues)
        self.aggregator = aggregator_prompt_template | aggregator_bound_llm


    def expand(state: FileConsistencyIssuesState, *, config: RunnableConfig):
        pass


    def score():
        pass


    def aggregate():
        pass


    def prune():
        pass


    def should_terminate():
        pass


    @traceable(name="Inconsistency Check Pipeline")
    def __call__(self, dto: InconsistencyCheckPipelineExecutionDTO, **kwargs):
        """
        Runs the pipeline to check for inconsistencies in the exercise
        :param dto: execution data transfer object
        :param kwargs: The keyword arguments
        """

        if not dto.exercise:
            logger.error("Inconsistency check pipeline requires an exercise")
            raise ValueError("Exercise is required")

        logger.info("Running inconsistency check pipeline...")
        self.callback.in_progress()


        # Create the graph
        builder = StateGraph(state_schema=FileConsistencyIssuesState, config_schema=Configuration)
        
        # Add nodes
        builder.add_node("expand", self.expand)
        builder.add_node("score", self.score)
        builder.add_node("prune", self.prune)

        # Add edges
        builder.add_edge(START, "expand")    
        builder.add_edge("expand", "score")
        builder.add_edge("score", "prune")
        
        builder.add_conditional_edges("prune", should_terminate, path_map=["expand", "__end__"])
        builder.add_edge(START, "node_1")
        builder.add_conditional_edges("node_1", decide_mood)
        builder.add_edge("node_2", END)
        builder.add_edge("node_3", END)
        
        graph = builder.compile()

        # graph.get_graph().draw_mermaid_png()
        
        graph.invoke({"graph_state" : "Hi, this is Lance."})
        
        # def multiply(a: int, b: int) -> int:
        #     """Multiply a and b.

        #     Args:
        #         a: first int
        #         b: second int
        #     """
        #     return a * b

        # llm_with_tools = llm.bind_tools([multiply])

        template_repository = "\n".join(
            f"<File path='{file_path}'>\n{file_content}</File>"
            for file_path, file_content in dto.exercise.template_repository.items()
        )

        response: str = self.pipeline.invoke(
            {
                "problem_statement": dto.exercise.problem_statement,
                "template_repository": template_repository,
            }
        )

        self._append_tokens(self.llm.tokens, PipelineEnum.IRIS_INCONSISTENCY_CHECK)

        self.callback.done(final_result=response, tokens=self.tokens)
