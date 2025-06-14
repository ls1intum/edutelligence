import json
import logging
from pprint import pprint

import langchain_core
from langchain.agents import create_tool_calling_agent, AgentExecutor
from langchain_core.language_models.chat_models import SimpleChatModel
from langchain_core.messages import AIMessage, HumanMessage, BaseMessage, SystemMessage
from langchain_core.prompt_values import ChatPromptValue
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import BaseTool
from typing import List, Optional, Any, Union
from pydantic import BaseModel
import requests
from copy import deepcopy

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# noinspection PyShadowingNames
class LogosLLM(SimpleChatModel, BaseModel):
    logos_key: str
    path: str
    deployment_name: Union[str, None]
    api_version: Union[str, None]
    base_url: str = "http://127.0.0.1:8000"
    tools: Optional[List[BaseTool]] = None

    def _llm_type(self) -> str:
        return "logos-llm"

    def bind_tools(self, tools: List[BaseTool]) -> "LogosLLM":
        new_llm = deepcopy(self)
        new_llm.tools = tools
        return new_llm

    def _call(self, messages: langchain_core.prompt_values.ChatPromptValue) -> str:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.logos_key}",
            "deployment_name": self.deployment_name,
            "api_version": self.api_version
        }
        prompt_parts = []
        for msg in messages.messages:
            if isinstance(msg, HumanMessage):
                prompt_parts.append(msg.content)
            elif isinstance(msg, SystemMessage):
                prompt_parts.append(msg.content)
        prompt = "\n".join(prompt_parts)

        data = {
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.5
        }

        response = requests.post(f"{self.base_url}{self.path}", json=data, headers=headers)

        if response.status_code != 200:
            raise Exception(f"Logos API Error {response.status_code}: {response.text}")

        return json.dumps(response.json())

    def invoke(self, messages: List[BaseMessage], **kwargs) -> AIMessage:
        output = self._call(messages)
        return AIMessage(content=output)

    def build_agent(self):
        # Prompt vorbereiten
        prompt = ChatPromptTemplate.from_messages([
            ("system", ""),
            ("human", "{input}"),
            MessagesPlaceholder(variable_name="agent_scratchpad"),
        ]
        )

        # Agent bauen (nutzt Tool automatisch!)
        agent = create_tool_calling_agent(self, tools=[], prompt=prompt)
        return AgentExecutor(agent=agent, tools=[], verbose=True)


# Example usage
if __name__ == "__main__":
    try:
        logger.info("Initializing the LogosLLM")
        llm = LogosLLM(
            logos_key="",
            deployment_name="gpt-4o",
            api_version="2024-08-01-preview",
            path="/v1/chat/completions"
        )

        agent_executor = llm.build_agent()

        # Eingabe
        user_query = "Tell me a funfact about the sassanid empire!"

        # Automatische Ausführung (inkl. Tool-Call und Ergebnisverarbeitung)
        response = agent_executor.invoke({"input": user_query})
        pprint(json.loads(response["output"]))
    except Exception as e:
        logger.error(f"An error occurred: {e}", exc_info=True)
