import logging
from datetime import datetime
from typing import List, Optional, Tuple

from iris.common.pyris_message import IrisMessageRole, PyrisMessage
from iris.domain import FeatureDTO
from iris.domain.text_exercise_chat_pipeline_execution_dto import (
    TextExerciseChatPipelineExecutionDTO,
)
from iris.llm import (
    CompletionArguments,
    ModelVersionRequestHandler,
)
from iris.llm.external.model import LanguageModel
from iris.pipeline import Pipeline
from iris.pipeline.prompts.text_exercise_chat_prompts import (
    fmt_extract_sentiments_prompt,
    fmt_sentiment_analysis_prompt,
    fmt_system_prompt,
)
from iris.pipeline.shared.utils import filter_variants_by_available_models
from iris.web.status.status_update import TextExerciseChatCallback

logger = logging.getLogger(__name__)


class TextExerciseChatPipeline(Pipeline):
    """TextExerciseChatPipeline handles text exercise chat processing by extracting sentiments from user input and
    generating appropriate responses based on exercise details and conversation context.
    """

    callback: TextExerciseChatCallback
    request_handler: ModelVersionRequestHandler
    variant: str

    def __init__(
        self,
        callback: Optional[TextExerciseChatCallback] = None,
        variant: str = "default",
    ):
        super().__init__(implementation_id="text_exercise_chat_pipeline_reference_impl")
        self.callback = callback
        self.variant = variant

        if variant == "advanced":
            model = "gpt-4.1"
        else:
            model = "gpt-4.1-nano"

        self.request_handler = ModelVersionRequestHandler(version=model)

    @classmethod
    def get_variants(cls, available_llms: List[LanguageModel]) -> List[FeatureDTO]:
        variant_specs = [
            (
                ["gpt-4.1-nano"],
                FeatureDTO(
                    id="default",
                    name="Default",
                    description="Uses a smaller model for faster and cost-efficient responses.",
                ),
            ),
            (
                ["gpt-4.1"],
                FeatureDTO(
                    id="advanced",
                    name="Advanced",
                    description="Uses a larger chat model, balancing speed and quality.",
                ),
            ),
        ]

        return filter_variants_by_available_models(
            available_llms, variant_specs, pipeline_name="TextExerciseChatPipeline"
        )

    def __call__(
        self,
        dto: TextExerciseChatPipelineExecutionDTO,
        **kwargs,
    ):
        """
        Run the text exercise chat pipeline.
        This consists of a sentiment analysis step followed by a response generation step.
        """
        if not dto.exercise:
            raise ValueError("Exercise is required")
        if not dto.conversation:
            raise ValueError("Conversation with at least one message is required")

        sentiments = self.categorize_sentiments_by_relevance(dto)
        self.callback.done("Responding")

        response = self.respond(dto, sentiments)
        self.callback.done(final_result=response)

    def categorize_sentiments_by_relevance(
        self, dto: TextExerciseChatPipelineExecutionDTO
    ) -> Tuple[List[str], List[str], List[str]]:
        """
        Extracts the sentiments from the user's input and categorizes them as "Ok", "Neutral", or "Bad" in terms of
        relevance to the text exercise at hand.
        Returns a tuple of lists of sentiments in each category.
        """
        extract_sentiments_prompt = fmt_extract_sentiments_prompt(
            exercise_name=dto.exercise.title,
            course_name=dto.exercise.course.name,
            course_description=dto.exercise.course.description,
            problem_statement=dto.exercise.problem_statement,
            previous_message=(
                dto.conversation[-2].contents[0].text_content
                if len(dto.conversation) > 1
                else None
            ),
            user_input=dto.conversation[-1].contents[0].text_content,
        )
        extract_sentiments_prompt = PyrisMessage(
            sender=IrisMessageRole.SYSTEM,
            contents=[{"text_content": extract_sentiments_prompt}],
        )
        response = self.request_handler.chat(
            [extract_sentiments_prompt], CompletionArguments(), tools=None
        )
        response = response.contents[0].text_content
        sentiments = ([], [], [])
        for line in response.split("\n"):
            line = line.strip()
            if line.startswith("Ok: "):
                sentiments[0].append(line[4:])
            elif line.startswith("Neutral: "):
                sentiments[1].append(line[10:])
            elif line.startswith("Bad: "):
                sentiments[2].append(line[5:])
        return sentiments

    def respond(
        self,
        dto: TextExerciseChatPipelineExecutionDTO,
        sentiments: Tuple[List[str], List[str], List[str]],
    ) -> str:
        """
        Actually respond to the user's input.
        This takes the user's input and the conversation so far and generates a response.
        """
        system_prompt = PyrisMessage(
            sender=IrisMessageRole.SYSTEM,
            contents=[
                {
                    "text_content": fmt_system_prompt(
                        exercise_name=dto.exercise.title,
                        course_name=dto.exercise.course.name,
                        course_description=dto.exercise.course.description,
                        problem_statement=dto.exercise.problem_statement,
                        start_date=str(dto.exercise.start_date),
                        end_date=str(dto.exercise.end_date),
                        current_date=str(datetime.now()),
                        current_submission=dto.current_submission,
                    )
                }
            ],
        )
        sentiment_analysis = PyrisMessage(
            sender=IrisMessageRole.SYSTEM,
            contents=[
                {
                    "text_content": fmt_sentiment_analysis_prompt(
                        respond_to=sentiments[0] + sentiments[1],
                        ignore=sentiments[2],
                    )
                }
            ],
        )
        prompts = (
            [system_prompt]
            + dto.conversation[:-1]
            + [sentiment_analysis]
            + dto.conversation[-1:]
        )

        response = self.request_handler.chat(
            prompts, CompletionArguments(temperature=0.4), tools=None
        )
        return response.contents[0].text_content
