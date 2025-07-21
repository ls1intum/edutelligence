from langchain.chat_models import init_chat_model
from langfuse.callback import CallbackHandler

from .models import RewriteProblemStatementRequest, RewriteProblemStatementResponse
from .prompts import rewrite_prompt

langfuse_handler = CallbackHandler()


class ProblemStatementRewrite:

    def __init__(self, model_name: str):
        self.model = init_chat_model(model_name)

    def rewrite(
        self, request: RewriteProblemStatementRequest
    ) -> RewriteProblemStatementResponse:

        input_data = {"text": request.text}

        rewriter = rewrite_prompt | self.model

        # Rewrite the text
        response = rewriter.invoke(
            input_data,
            config={
                "callbacks": [langfuse_handler],
                "run_name": "problem_statement_rewrite",
            },
        )
        rewritten_text = response.content.strip()

        return RewriteProblemStatementResponse(rewritten_text=rewritten_text)
