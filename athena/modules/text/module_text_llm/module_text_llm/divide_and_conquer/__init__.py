from typing import Literal

from module_text_llm.approach_config import ApproachConfig


class DivideAndConquerConfig(ApproachConfig):
    type: Literal['divide_and_conquer'] = 'divide_and_conquer'
    