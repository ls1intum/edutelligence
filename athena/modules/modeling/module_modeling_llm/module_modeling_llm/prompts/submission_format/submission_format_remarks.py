from module_modeling_llm.helpers.models.diagram_types import DiagramType
from module_modeling_llm.prompts.submission_format.bpmn import \
    submission_format_remarks as bpmn_submission_format_remarks
from module_modeling_llm.prompts.submission_format.general import \
    submission_format_remarks as general_submission_format_remarks


def get_submission_format_remarks(diagram_type: DiagramType) -> str:
    match diagram_type:
        case DiagramType.CLASS_DIAGRAM:
            return general_submission_format_remarks
        case DiagramType.OBJECT_DIAGRAM:
            return general_submission_format_remarks
        case DiagramType.ACTIVITY_DIAGRAM:
            return general_submission_format_remarks
        case DiagramType.USE_CASE_DIAGRAM:
            return general_submission_format_remarks
        case DiagramType.COMMUNICATION_DIAGRAM:
            return general_submission_format_remarks
        case DiagramType.COMPONENT_DIAGRAM:
            return general_submission_format_remarks
        case DiagramType.DEPLOYMENT_DIAGRAM:
            return general_submission_format_remarks
        case DiagramType.PETRI_NET:
            return general_submission_format_remarks
        case DiagramType.REACHABILITY_GRAPH:
            return general_submission_format_remarks
        case DiagramType.SYNTAX_TREE:
            return general_submission_format_remarks
        case DiagramType.FLOWCHART:
            return general_submission_format_remarks
        case DiagramType.BPMN:
            return bpmn_submission_format_remarks
