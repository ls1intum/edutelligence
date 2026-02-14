import logging
from iris.llm import CompletionArguments, ModelVersionRequestHandler
from iris.llm.langchain import IrisLangchainChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
from jinja2 import Template

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def evaluate(evaluation_prompt: str, instances: int, output_to_evaluate: str, task: str, template: str, code: str):
    # Create LLM for evaluation
    completion_args = CompletionArguments(temperature=0.6, max_tokens=2000)
    llm = IrisLangchainChatModel(
        request_handler=ModelVersionRequestHandler(version="gpt-4.1-mini"),
        completion_args=completion_args
    )

    rendered_prompt = Template(evaluation_prompt).render(
        task=task,
        template=template,
        code=code
    )

    prompt = ChatPromptTemplate.from_messages(
        [
            SystemMessage(content=rendered_prompt),
            HumanMessage(content=output_to_evaluate),
        ]
    )

    ok = 0

    for i in range(instances):
        response = (prompt | llm | StrOutputParser()).invoke({})
        logger.info(f"LLM evaluation instance {i}: response: {response}")
        if "!ok!" in response:
            ok += 1
        elif not "!bad!" in response:
            logger.error(f"Evaluation result of instance {i} is invalid!")

    verdict = ok / instances

    logger.info(f"Verdict is {verdict}")

    return verdict
