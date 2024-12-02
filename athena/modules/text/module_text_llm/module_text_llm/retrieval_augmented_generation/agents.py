from langchain_openai import ChatOpenAI
from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.prompts import ChatPromptTemplate
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain.tools.retriever import create_retriever_tool
from pydantic import BaseModel, Field
from langchain_core.tools import tool
import glob
from typing import List, Optional
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
    def __init__(self, session_id="test-session"):
        # Initialize model, memory, and tools
        self.model = ChatOpenAI(model="gpt-4o-2024-08-06") #gpt-4o-2024-08-06 , gpt-4o-mini
        self.memory = InMemoryChatMessageHistory(session_id=session_id)
        all_docs = []
        file_paths = glob.glob("module_text_llm/retrieval_augmented_generation/pdfs/*.pdf")
        self.approach_config = None
        for file_path in file_paths:
            loader = PyPDFLoader(file_path)
            docs = loader.load()
            all_docs += docs

        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        splits = text_splitter.split_documents(all_docs)
        vectorstore = InMemoryVectorStore.from_documents(
            documents=splits, embedding=OpenAIEmbeddings()
        )

        retriever = vectorstore.as_retriever()
        retriever_tool = create_retriever_tool(retriever, name="retrieve_document", description="Retrieves the pdf documents from the relevant lecture")
   
        # Define the prompt template with a system message placeholder


        # Define the tools
        self.tools = [retriever_tool,AssessmentModel]
        # structured_llm = self.model.with_structured_output(AssessmentModel)
        # Create the agent and executor

        
    def setConfig(self,approach_config):
        self.approach_config = approach_config
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.approach_config.generate_suggestions_prompt.system_message),
                ("human", "{submission}"),
                ("placeholder", "{agent_scratchpad}"),  # Internal for steps created through function calling
            ])
        self.agent = create_tool_calling_agent(self.model, self.tools, self.prompt)
        self.agent_executor = AgentExecutor(agent=self.agent, tools=self.tools)

        # Default configuration for the agent
        self.config = {"configurable": {"session_id": "test-session"}}
        
    def call_agent(self, prompt):
        """Calls the agent with a prompt and returns the response output.
        Optionally takes a system_message to update the agent's behavior dynamically."""
        from langchain_core.output_parsers import PydanticOutputParser

        parser = PydanticOutputParser(pydantic_object=AssessmentModelParse)

        chain = self.agent_executor | parser 
        response = self.agent_executor.invoke(
            input = prompt#  , "system_message": system_message
        )
        import json
        print(response)
        res = AssessmentModelParse.parse_obj(json.loads(response["output"]))
        return res


#      system_message = """You are an AI tutor for text assessment at a prestigious university.

# # Task
# Create graded feedback suggestions for a student's text submission that a human tutor would accept. Meaning, the feedback you provide should be applicable to the submission with little to no modification.

# You have access to the provided document lecture slides to help you provide feedback. 
# If you do use them, please reference the title and the page on your feedback.
# Write it down epxlicitly when lecture slides or contents are relvant. 

# # Style
# 1. Constructive, 2. Specific, 3. Balanced, 4. Clear and Concise, 5. Actionable, 6. Educational, 7. Contextual

# Make use of the lecture slides provided. State clearly on your feedback which lecture you are using. If you
# believe that the student could benefit from the slide refer it on your feedback.

# The grading instructions are there to guide you on which criteria to give points. 
# You can comment with 0 points about grammar and spelling errors, but you should not give or remove points for them.

# # Problem statement
# {problem_statement}

# # Example solution
# {example_solution}

# # Grading instructions
# {grading_instructions}
# Max points: {max_points}, bonus points: {bonus_points}    
# Respond only in json with the provided Assessment Feedback schema.
# """