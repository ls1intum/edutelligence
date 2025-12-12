from iris.web.routers.health.health_model import ModuleStatus, ServiceStatus
from iris.web.routers.health.Pipelines.checker import evaluate_feature
from iris.web.routers.health.Pipelines.features import Features
from iris.web.routers.health.Pipelines.summarize import derive_status, format_summary

from iris.llm.llm_manager import LlmManager  # noqa: E402 # isort: skip


def check_pipelines_health() -> tuple[str, ModuleStatus]:
    module_key = "Pipelines"
    try:
        llms = LlmManager().entries
    except Exception as e:  # pylint: disable=broad-except
        return module_key, ModuleStatus(status=ServiceStatus.DOWN, error=str(e))
    available_models = {e.model for e in llms}
    available_ids = {e.id for e in llms}
    results = [evaluate_feature(f, available_models, available_ids) for f in Features]
    status = derive_status(results)
    summary = format_summary(results)
    return module_key, ModuleStatus(status=status, metaData=summary)
