from iris.web.routers.health.health_model import ModuleStatus
from iris.web.routers.health.Pipelines.checker import evaluate_feature
from iris.web.routers.health.Pipelines.features import Features
from iris.web.routers.health.Pipelines.summarize import derive_status, format_summary

from iris.llm.llm_manager import LlmManager  # noqa: E402 # isort: skip


def check_pipelines_health() -> tuple[str, ModuleStatus]:
    module_key = "Pipelines"
    available = {e.model for e in LlmManager().entries}
    results = [evaluate_feature(f, available) for f in Features]
    status = derive_status(results)
    summary = format_summary(results)
    return module_key, ModuleStatus(status=status, metaData=summary)
