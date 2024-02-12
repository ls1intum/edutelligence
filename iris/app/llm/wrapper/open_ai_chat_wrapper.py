from openai.lib.azure import AzureOpenAI
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionMessage

from domain import IrisMessage, IrisMessageRole
from llm import CompletionArguments
from llm.wrapper import AbstractLlmChatCompletionWrapper


def convert_to_open_ai_messages(
    messages: list[IrisMessage],
) -> list[ChatCompletionMessageParam]:
    return [
        {"role": message.role.value, "content": message.text} for message in messages
    ]


def convert_to_iris_message(message: ChatCompletionMessage) -> IrisMessage:
    # Get IrisMessageRole from the string message.role
    message_role = IrisMessageRole(message.role)
    return IrisMessage(role=message_role, text=message.content)


class BaseOpenAIChatCompletionWrapper(AbstractLlmChatCompletionWrapper):

    def __init__(self, client, model: str, **kwargs):
        super().__init__(**kwargs)
        self.client = client
        self.model = model

    def chat_completion(
        self, messages: list[any], arguments: CompletionArguments
    ) -> IrisMessage:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=convert_to_open_ai_messages(messages),
            temperature=arguments.temperature,
            max_tokens=arguments.max_tokens,
            stop=arguments.stop,
        )
        return convert_to_iris_message(response.choices[0].message)


class OpenAIChatCompletionWrapper(BaseOpenAIChatCompletionWrapper):

    def __init__(self, model: str, api_key: str, **kwargs):
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        model = model
        super().__init__(client, model, **kwargs)

    def __str__(self):
        return f"OpenAIChat('{self.model}')"


class AzureChatCompletionWrapper(BaseOpenAIChatCompletionWrapper):

    def __init__(
        self,
        model: str,
        endpoint: str,
        azure_deployment: str,
        api_version: str,
        api_key: str,
        **kwargs,
    ):
        client = AzureOpenAI(
            azure_endpoint=endpoint,
            azure_deployment=azure_deployment,
            api_version=api_version,
            api_key=api_key,
        )
        model = model
        super().__init__(client, model, **kwargs)

    def __str__(self):
        return f"AzureChat('{self.model}')"
