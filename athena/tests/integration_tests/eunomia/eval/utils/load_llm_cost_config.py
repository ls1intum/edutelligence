import yaml
from pathlib import Path
from pydantic import ValidationError
from eval.models.schemas.external.llm_costs_config import LLMCostsConfig

def load_llm_cost_config(scenario_dir: Path) -> LLMCostsConfig:
    llm_cost_path = scenario_dir / "llm_cost.yml"
    if not llm_cost_path.exists():
        # You might choose to return a default config or raise an error.
        # Here we raise an error because costs are critical.
        raise FileNotFoundError(f"No llm_cost.yml found in scenario directory '{scenario_dir}'.")

    with open(llm_cost_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    try:
        config = LLMCostsConfig(**data)
    except ValidationError as ve:
        raise ValueError(f"Invalid LLM cost configuration: {ve}") from ve

    return config
