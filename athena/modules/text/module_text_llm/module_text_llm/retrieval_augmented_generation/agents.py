from langchain_openai import ChatOpenAI
from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.prompts import ChatPromptTemplate
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.vectorstores import InMemoryVectorStore
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain.tools.retriever import create_retriever_tool
from pydantic import BaseModel, Field
from langchain_core.tools import tool
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain.chains import create_retrieval_chain

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
    def __init__(self):
        # TODO make model selecteable later
        self.model = ChatOpenAI(model="gpt-4o-2024-08-06") #gpt-4o-2024-08-06 , gpt-4o-mini
        self.outputModel = ChatOpenAI(model="gpt-4o-mini")
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

        self.retriever = vectorstore.as_retriever()
        retriever_tool = create_retriever_tool(self.retriever, name="retrieve_document", description="Retrieves the pdf documents from the relevant lecture")
        self.tools = [retriever_tool,AssessmentModel]
        
    def setConfig(self,approach_config):
        self.approach_config = approach_config
        self.prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.approach_config.generate_suggestions_prompt.system_message),
                ("human", "{submission}"),
                ("placeholder", "{agent_scratchpad}"),
            ])
        self.agent = create_tool_calling_agent(self.model, self.tools, self.prompt)
        self.agent_executor = AgentExecutor(agent=self.agent, tools=self.tools)
        # Default configuration for the agent
        self.config = {"configurable": {"session_id": "test-session"}}
        
    def call_agent(self, prompt):
        """Calls the agent with a prompt and returns the response output.
        Optionally takes a system_message to update the agent's behavior dynamically."""
        response = self.agent_executor.invoke(
            input = prompt
        )
        print(response)
        res = self.outputModel.with_structured_output(AssessmentModelParse).invoke(f"Format the following output {response}") 
        return res
    