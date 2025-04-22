from typing import List
from pydantic import BaseModel, Field

from langchain_core.messages import ChatMessage, HumanMessage, ToolMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder, SystemMessagePromptTemplate

from langfuse.callback import CallbackHandler

from hyperion.models import get_model
from hyperion.logger import logger
from hyperion.settings import settings

from .prompts import system_message

callbacks = []
if settings.langfuse_enabled:
    langfuse_handler = CallbackHandler()
    langfuse_handler.auth_check()
    callbacks.append(langfuse_handler)

ChatModel = get_model(settings.MODEL_NAME)
model = ChatModel().with_config(callbacks=callbacks)


class update_draft_problem_statement(BaseModel):
    """Update the draft problem statement, if you are sure that the update is expected."""
    
    updated_problem_statement: str = Field(..., description="The updated problem statement.")
    stdout: str = Field(..., description="Very short summary of the update, will be shown to the user.")


def generate_chat_response(messages: List[ChatMessage], input_query: str, draft_problem_statement: str):
    prompt = ChatPromptTemplate.from_messages(
        [
            SystemMessagePromptTemplate.from_template(system_message),
            MessagesPlaceholder(variable_name="messages"),
            HumanMessage(input_query),
        ]
    )
    
    tools = [update_draft_problem_statement]
    
    model_with_tools = model.bind_tools(tools, tool_choice="auto")
    chain = prompt | model_with_tools
        
    response = chain.invoke({
        "draft_problem_statement": draft_problem_statement or "<Empty draft problem statement, assist the instructor>",
        "messages": messages,
        "input_text": input_query,
    })
    
    logger.info(f"Chat response: {response.content}")
    logger.info(f"Response details: {response.tool_calls}")
    
    if response.tool_calls:
        tool_call = response.tool_calls[0] # We only have one tool call as of now
        # if tool_call["name"] == "update_draft_problem_statement" is always true as of now
        
        # Maybe not the right way to do it but it works, passing ToolMessage later to the LLM causes issues 
        return ToolMessage(
            tool_call_id=tool_call["id"],
            content=tool_call["args"]["stdout"],
            artifact=tool_call["args"]["updated_problem_statement"],
        )

    return AIMessage(response.content)
