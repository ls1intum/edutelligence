from enum import Enum


class DiagramType(str, Enum):
    CLASS_DIAGRAM = "ClassDiagram"
    OBJECT_DIAGRAM = "ObjectDiagram"
    ACTIVITY_DIAGRAM = "ActivityDiagram"
    USE_CASE_DIAGRAM = "UseCaseDiagram"
    COMMUNICATION_DIAGRAM = "CommunicationDiagram"
    COMPONENT_DIAGRAM = "ComponentDiagram"
    DEPLOYMENT_DIAGRAM = "DeploymentDiagram"
    PETRI_NET = "PetriNet"
    REACHABILITY_GRAPH = "ReachabilityGraph"
    SYNTAX_TREE = "SyntaxTree"
    FLOWCHART = "Flowchart"
    BPMN = "BPMN"
