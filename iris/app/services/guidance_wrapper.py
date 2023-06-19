import guidance

from app.config import settings
from app.models.dtos import Content, ContentType, LLMModel


class GuidanceWrapper:
    """A wrapper service to all guidance package's methods."""

    # TODO: will change to use yml config in the next PR
    MODELS_MAPPING = {LLMModel.GPT35_TURBO: "gpt-3.5-turbo"}

    def __init__(
        self, model: LLMModel, handlebars: str, parameters=None
    ) -> None:
        if parameters is None:
            parameters = {}

        self.model = model
        self.handlebars = handlebars
        self.parameters = parameters

    def query(self) -> Content:
        """Get response from a chosen LLM model.

        Returns:
            Text content object with LLM's response.

        Raises:
            ValueError: if handlebars do not generate 'response'
        """

        template = guidance(self.handlebars)
        result = template(
            llm=self._get_llm(),
            **self.parameters,
        )

        if "response" not in result:
            raise ValueError("The handlebars do not generate 'response'")

        return Content(type=ContentType.TEXT, textContent=result["response"])

    def _get_llm(self):
        return guidance.llms.OpenAI(
            model=self.MODELS_MAPPING[self.model.value],
            token=settings.openai_token,
            api_base=settings.openai_api_base,
            api_type=settings.openai_api_type,
            api_version=settings.openai_api_version,
            deployment_id=settings.openai_deployment_id,
        )
