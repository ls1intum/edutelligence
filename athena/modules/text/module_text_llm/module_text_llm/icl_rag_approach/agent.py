from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_community.chat_models import ChatOllama # type: ignore
from pydantic import BaseModel, Field
from langchain_core.tools import tool
from module_text_llm.helpers.feedback_icl.retrieve_rag_context_icl import retrieve_rag_context_icl
from typing import List, Optional
from langchain.agents import create_react_agent,AgentType
from langchain.agents import initialize_agent
from langchain.tools import Tool


# HERE WE NEED TO ADD A TOOL FOR RETRIEVAL.
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

# @tool
def retrieve_rag_context_single(submission_segment: str) -> str:
    """
    This method takes a segment from a submission and for a given exercise id, 
    returns feedback that has been given for similar texts.

    Args:
        submission_segment: A segment of the submission.
        exercise_id: The id of the exercise.

    Returns:
        str: A formatted string of feedbacks which reference text similar to the submission_segment.
    """
    return retrieve_rag_context_icl(submission_segment,3004)

def generate_assessment(full_information: str) -> str:
    """
    This method takes a segment from a submission and for a given exercise id, 
    returns feedback that has been given for similar texts.

    Args:
        submission_segment: A segment of the submission.
        exercise_id: The id of the exercise.

    Returns:
        str: A formatted string of feedbacks which reference text similar to the submission_segment."""
    return "I assess this submission with 3 credits. One for each criterion"

rag_tool = Tool(
    name="retrieve_rag_context_single",
    func=retrieve_rag_context_single,
    description="Fetches previous tutor feedbacks and the student text that this reference was given to."
)
Lookup = Tool(
    name="Lookup",
    func=retrieve_rag_context_single,
    description="Fetches previous tutor feedbacks and the student text that this reference was given to."
)
Search = Tool(
    name="Search",
    func=retrieve_rag_context_single,
    description="Fetches previous tutor feedbacks and the student text that this reference was given to."
)

generate_assessment_tool = Tool(
    name="generate_assessment",
    func=generate_assessment,
    description="Generates an assessment based on the full known information")
# Output Object
class FeedbackModel(BaseModel):
    title: str = Field(description="Very short title, i.e. feedback category or similar", example="Logic Error")
    description: str = Field(description="Feedback description")
    line_start: Optional[int] = Field(description="Referenced line number start, or empty if unreferenced")
    line_end: Optional[int] = Field(description="Referenced line number end, or empty if unreferenced")
    credits: float = Field(0.0, description="Number of points received/deducted")
    grading_instruction_id: Optional[int] = Field(
        description="ID of the grading instruction that was used to generate this feedback, or empty if no grading instruction was used"
    )

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
        self.isOllama = False
        if isinstance(self.model, ChatOllama):
            self.isOllama = True
        self.outputModel = ChatOpenAI(model="gpt-4o-mini")
        self.approach_config = None
        self.openai_tools = [retrieve_rag_context,AssessmentModel]
        self.ollama_tools = [rag_tool]

        self.setConfig(config)
    
        
    def setConfig(self,approach_config):
        self.approach_config = approach_config
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.approach_config.generate_suggestions_prompt.system_message),
                ("human", "{submission}"),
                ("placeholder", "{agent_scratchpad}"),
            ])
        if self.isOllama:
            self.agent = initialize_agent(
            agent = AgentType.STRUCTURED_CHAT_ZERO_SHOT_REACT_DESCRIPTION,
            llm=self.model,
            tools=self.ollama_tools, 
            prompt=self.prompt,
            handle_parsing_errors=True,max_iterations=7)
        else:
            self.agent = create_tool_calling_agent(self.model, self.openai_tools , self.prompt)
        self.agent_executor = AgentExecutor(agent=self.agent, tools=self.openai_tools)
        # Default configuration for the agent
        self.config = {"configurable": {"session_id": "test-session"}}
        
    def call_agent(self, prompt):
        """Calls the agent with a prompt and returns the response output.
        Optionally takes a system_message to update the agent's behavior dynamically."""
        if self.isOllama:
            # return None
            response = self.agent.run(input = prompt)
            # response = self.agent_executor.invoke(
            #     input = prompt,
            # )
        else:
            response = self.agent_executor.invoke(
            input = prompt
        )
        
        # print(response)
        # Try to parse first and then use the backup mini4
        res = self.outputModel.with_structured_output(AssessmentModelParse).invoke(f"Format the following output {response}") 
        return res
    
    