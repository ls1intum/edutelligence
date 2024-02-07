import json
from typing import Optional
from xml.dom import minidom
from xml.etree import ElementTree

from module_modelling_llm.helpers.models.diagram_types import DiagramType
from module_modelling_llm.helpers.serializers.bpmn_serializer import BPMNSerializer


class DiagramModelSerializer:

    @staticmethod
    def serialize_model(model: dict) -> tuple[Optional[str], Optional[dict[str, str]]]:
        """
        Serialize a given Apollon diagram model to string. At the moment, this method returns a native JSON
        serialization of the diagram for all diagram types other than BPMN diagrams. This diagram type is serialized in
        the BPMN 2.0 XML format as this format is following an official standard and therefore well understood by most
        LLMs.

        The function returns a tuple consisting of string representing the serialized diagram and a dictionary allowing
        to map shortened IDs back to full IDs if needed.
        """
        match model.get("type"):
            case DiagramType.CLASS_DIAGRAM:
                # TODO: Evaluate if there is a more sensible serialization format for this diagram type
                return json.dumps(model), None
            case DiagramType.OBJECT_DIAGRAM:
                # TODO: Evaluate if there is a more sensible serialization format for this diagram type
                return json.dumps(model), None
            case DiagramType.ACTIVITY_DIAGRAM:
                # TODO: Evaluate if there is a more sensible serialization format for this diagram type
                return json.dumps(model), None
            case DiagramType.USE_CASE_DIAGRAM:
                # TODO: Evaluate if there is a more sensible serialization format for this diagram type
                return json.dumps(model), None
            case DiagramType.COMMUNICATION_DIAGRAM:
                # TODO: Evaluate if there is a more sensible serialization format for this diagram type
                return json.dumps(model), None
            case DiagramType.COMPONENT_DIAGRAM:
                # TODO: Evaluate if there is a more sensible serialization format for this diagram type
                return json.dumps(model), None
            case DiagramType.DEPLOYMENT_DIAGRAM:
                # TODO: Evaluate if there is a more sensible serialization format for this diagram type
                return json.dumps(model), None
            case DiagramType.PETRI_NET:
                # TODO: Evaluate if there is a more sensible serialization format for this diagram type
                return json.dumps(model), None
            case DiagramType.REACHABILITY_GRAPH:
                # TODO: Evaluate if there is a more sensible serialization format for this diagram type
                return json.dumps(model), None
            case DiagramType.SYNTAX_TREE:
                # TODO: Evaluate if there is a more sensible serialization format for this diagram type
                return json.dumps(model), None
            case DiagramType.FLOWCHART:
                # TODO: Evaluate if there is a more sensible serialization format for this diagram type
                return json.dumps(model), None
            case DiagramType.BPMN:
                serializer = BPMNSerializer(
                    xsi_prefix=None,
                    bpmn_prefix=None,
                    bpmndi_prefix=None,
                    dc_prefix=None,
                    di_prefix=None
                )

                serialized_model: str = ElementTree.tostring(serializer.serialize(model, omit_layout_info=True),
                                                             encoding='utf8')

                reverse_id_map = serializer.id_shortener.get_reverse_id_map() if serializer.id_shortener else None

                # The use of minidom is only required here "pretty-print" the XML output for easier debugging
                return minidom.parseString(serialized_model).toprettyxml(indent="\t"), reverse_id_map

        return None, None
