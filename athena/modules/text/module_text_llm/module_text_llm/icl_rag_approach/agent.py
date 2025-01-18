from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain.agents import AgentExecutor, create_tool_calling_agent
from pydantic import BaseModel, Field
from langchain_core.tools import tool
from module_text_llm.helpers.feedback_icl.retrieve_rag_context_icl import retrieve_rag_context_icl
from module_text_llm.icl_rag_approach.prompt_generate_suggestions import FeedbackModel
from typing import List, Optional

@tool
def retrieve_rag_context(submission_segment: str ,exercise_id: int) -> str:
    """
    This method takes a segment from a submission and for a given exercise id, 
    returns feedback that has been given for similar texts.

    Args:
        submission_segment: A segment of the submission.
        exercise_id: The id of the exercise.

    Returns:
        str: A formatted string of feedbacks which reference text similar to the submission_segment.
    """
    return retrieve_rag_context_icl(submission_segment,exercise_id)

@tool
class AssessmentModel(BaseModel):
    """Collection of feedbacks making up an assessment"""
    
    feedbacks: List[FeedbackModel] = Field(description="Assessment feedbacks")
    
class AssessmentModelParse(BaseModel):
    """Collection of feedbacks making up an assessment"""
    
    feedbacks: List[FeedbackModel] = Field(description="Assessment feedbacks")
        
class TutorAgent:
    def __init__(self,config): 
        self.model = config.model.get_model()# ChatOpenAI(model="gpt-4o-2024-08-06") #gpt-4o-2024-08-06 , gpt-4o-mini
        self.outputModel = ChatOpenAI(model="gpt-4o-mini")
        self.approach_config = None
        self.openai_tools = [retrieve_rag_context,AssessmentModel]
        self.setConfig(config)
    
        
    def setConfig(self,approach_config):
        self.approach_config = approach_config
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.approach_config.generate_suggestions_prompt.system_message),
                ("human", "{submission}"),
                ("placeholder", "{agent_scratchpad}"),
            ])

        self.agent = create_tool_calling_agent(self.model, self.openai_tools , self.prompt)
        self.agent_executor = AgentExecutor(agent=self.agent, tools=self.openai_tools)
        self.config = {"configurable": {"session_id": "test-session"}}
        
    def call_agent(self, prompt):
        """Calls the agent with a prompt and returns the response output."""

        response = self.agent_executor.invoke(
            input = prompt
        )
        
        res = self.outputModel.with_structured_output(AssessmentModelParse).invoke(f"Format the following output {response}") 
        return res
    
    