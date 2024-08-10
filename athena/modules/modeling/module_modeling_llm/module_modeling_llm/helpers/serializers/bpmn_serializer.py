import uuid
from enum import Enum
from functools import reduce
from itertools import chain
from typing import Optional
from xml.etree import ElementTree

DEFAULT_XSI_PREFIX = "xsi"
DEFAULT_BPMN_PREFIX = "bpmn"
DEFAULT_BPMNDI_PREFIX = "bpmndi"
DEFAULT_DC_PREFIX = "dc"
DEFAULT_DI_PREFIX = "di"

INTERMEDIATE_CATCH_EVENT = "intermediateCatchEvent"
INTERMEDIATE_THROW_EVENT = "intermediateThrowEvent"


class BPMNElementType(str, Enum):
    BPMN_ANNOTATION = "BPMNAnnotation"
    BPMN_CALL_ACTIVITY = "BPMNCallActivity"
    BPMN_DATA_OBJECT = "BPMNDataObject"
    BPMN_DATA_STORE = "BPMNDataStore"
    BPMN_END_EVENT = "BPMNEndEvent"
    BPMN_GATEWAY = "BPMNGateway"
    BPMN_GROUP = "BPMNGroup"
    BPMN_INTERMEDIATE_EVENT = "BPMNIntermediateEvent"
    BPMN_POOL = "BPMNPool"
    BPMN_START_EVENT = "BPMNStartEvent"
    BPMN_SUBPROCESS = "BPMNSubprocess"
    BPMN_SWIMLANE = "BPMNSwimlane"
    BPMN_TASK = "BPMNTask"
    BPMN_TRANSACTION = "BPMNTransaction"


class BPMNFlowType(str, Enum):
    SEQUENCE = "sequence"
    MESSAGE = "message"


class BPMNStartEventType(str, Enum):
    DEFAULT = "default"
    MESSAGE = "message"
    TIMER = "timer"
    CONDITIONAL = "conditional"
    SIGNAL = "signal"


class BPMNIntermediateEventType(str, Enum):
    DEFAULT = "default"
    MESSAGE_CATCH = "message-catch"
    MESSAGE_THROW = "message-throw"
    TIMER_CATCH = "timer-catch"
    ESCALATION_CATCH = "escalation-catch"
    CONDITIONAL_CATCH = "conditional-catch"
    LINK_CATCH = "link-catch"
    LINK_THROW = "link-throw"
    COMPENSATION_THROW = "compensation-throw"
    SIGNAL_CATCH = "signal-catch"
    SIGNAL_THROW = "signal-throw"


class BPMNEndEventType(str, Enum):
    DEFAULT = "default"
    MESSAGE = "message"
    ESCALATION = "escalation"
    ERROR = "error"
    COMPENSATION = "compensation"
    SIGNAL = "signal"
    TERMINATE = "terminate"


class BPMNTaskType(str, Enum):
    DEFAULT = "default"
    USER = "user"
    SEND = "send"
    RECEIVE = "error"
    MANUAL = "manual"
    BUSINESS_RULE = "business-rule"
    SCRIPT = "script"


class BPMNGatewayType(str, Enum):
    COMPLEX = "complex"
    EVENT_BASED = "event-based"
    EXCLUSIVE = "exclusive"
    INCLUSIVE = "inclusive"
    PARALLEL = "parallel"


class IDShortener:
    id_map: dict[str, str] = {}
    id_counter: int = 0

    def shorten_id(self, id: str, prefix: Optional[str] = None) -> str:
        """
        Shorten an ID to a minimum length numeric ID. This function mainly serves the purpose to shorten IDs to decrease
        the token count for LLM queries.
        :param id: The ID that should be shortened
        :param prefix: An optional prefix for the shortened IDs
        """

        if prefix is None:
            prefix = "id"

        if id not in self.id_map:
            self.id_map[id] = f"{prefix}{'_' if prefix else ''}{self.id_counter}"
            self.id_counter += 1

        return self.id_map[id]

    def get_id_map(self) -> dict[str, str]:
        """
        Retrieve the dictionary used to map a given ID to a shortened ID
        """
        return self.id_map

    def get_reverse_id_map(self) -> dict[str, str]:
        """
        Retrieve a dictionary allowing to map a shortened ID back to a full ID
        """
        return {value: key for key, value in self.id_map.items()}

    def reset(self):
        """
        Reset the IDShortener's internal ID map
        """
        self.id_map = {}


class BPMNSerializer:
    __start_event_definition_map = {
        BPMNStartEventType.DEFAULT: None,
        BPMNStartEventType.MESSAGE: "messageEventDefinition",
        BPMNStartEventType.TIMER: "timerEventDefinition",
        BPMNStartEventType.SIGNAL: "signalEventDefinition",
        BPMNStartEventType.CONDITIONAL: "conditionalEventDefinition"
    }

    __intermediate_event_type_map = {
        BPMNIntermediateEventType.DEFAULT: INTERMEDIATE_CATCH_EVENT,
        BPMNIntermediateEventType.MESSAGE_CATCH: INTERMEDIATE_CATCH_EVENT,
        BPMNIntermediateEventType.MESSAGE_THROW: INTERMEDIATE_THROW_EVENT,
        BPMNIntermediateEventType.TIMER_CATCH: INTERMEDIATE_CATCH_EVENT,
        BPMNIntermediateEventType.ESCALATION_CATCH: INTERMEDIATE_CATCH_EVENT,
        BPMNIntermediateEventType.CONDITIONAL_CATCH: INTERMEDIATE_CATCH_EVENT,
        BPMNIntermediateEventType.LINK_CATCH: INTERMEDIATE_CATCH_EVENT,
        BPMNIntermediateEventType.LINK_THROW: INTERMEDIATE_THROW_EVENT,
        BPMNIntermediateEventType.COMPENSATION_THROW: INTERMEDIATE_THROW_EVENT,
        BPMNIntermediateEventType.SIGNAL_CATCH: INTERMEDIATE_CATCH_EVENT,
        BPMNIntermediateEventType.SIGNAL_THROW: INTERMEDIATE_THROW_EVENT
    }

    __intermediate_event_definition_map = {
        BPMNIntermediateEventType.DEFAULT: None,
        BPMNIntermediateEventType.MESSAGE_CATCH: "messageEventDefinition",
        BPMNIntermediateEventType.MESSAGE_THROW: "messageEventDefinition",
        BPMNIntermediateEventType.TIMER_CATCH: "timerEventDefinition",
        BPMNIntermediateEventType.ESCALATION_CATCH: "escalationEventDefinition",
        BPMNIntermediateEventType.CONDITIONAL_CATCH: "conditionalEventDefinition",
        BPMNIntermediateEventType.LINK_CATCH: "linkEventDefinition",
        BPMNIntermediateEventType.LINK_THROW: "linkEventDefinition",
        BPMNIntermediateEventType.COMPENSATION_THROW: "compensationEventDefinition",
        BPMNIntermediateEventType.SIGNAL_CATCH: "signalEventDefinition",
        BPMNIntermediateEventType.SIGNAL_THROW: "signalEventDefinition"
    }

    __end_event_definition_map = {
        BPMNEndEventType.DEFAULT: None,
        BPMNEndEventType.MESSAGE: "messageEventDefinition",
        BPMNEndEventType.ESCALATION: "escalationEventDefinition",
        BPMNEndEventType.ERROR: "errorEventDefinition",
        BPMNEndEventType.COMPENSATION: "compensationEventDefinition",
        BPMNEndEventType.SIGNAL: "signalEventDefinition",
        BPMNEndEventType.TERMINATE: "terminateEventDefinition"
    }

    __flow_type_map = {
        BPMNFlowType.SEQUENCE: "sequenceFlow",
        BPMNFlowType.MESSAGE: "messageFlow"
    }

    __task_type_map = {
        BPMNTaskType.DEFAULT: "task",
        BPMNTaskType.USER: "userTask",
        BPMNTaskType.SEND: "sendTask",
        BPMNTaskType.RECEIVE: "receive",
        BPMNTaskType.MANUAL: "manualTask",
        BPMNTaskType.BUSINESS_RULE: "businessRuleTask",
        BPMNTaskType.SCRIPT: "scriptTask"
    }

    __gateway_type_map = {
        BPMNGatewayType.COMPLEX: "exclusiveGateway",
        BPMNGatewayType.EVENT_BASED: "eventBasedGateway",
        BPMNGatewayType.EXCLUSIVE: "exclusiveGateway",
        BPMNGatewayType.INCLUSIVE: "inclusiveGateway",
        BPMNGatewayType.PARALLEL: "parallelGateway"
    }

    __xsi_prefix: Optional[str] = ""
    __bpmn_prefix: Optional[str] = ""
    __bpmndi_prefix: Optional[str] = ""
    __dc_prefix: Optional[str] = ""
    __di_prefix: Optional[str] = ""

    id_shortener: Optional[IDShortener] = None

    def __init__(self,
                 xsi_prefix: str | None = DEFAULT_XSI_PREFIX,
                 bpmn_prefix: str | None = DEFAULT_BPMN_PREFIX,
                 bpmndi_prefix: str | None = DEFAULT_BPMNDI_PREFIX,
                 dc_prefix: str | None = DEFAULT_DC_PREFIX,
                 di_prefix: str | None = DEFAULT_DI_PREFIX
                 ):
        """
        Create a new instance of the BPMNSerializer class. This class is used to serialize BPMN diagrams in Apollon's
        native JSON format into the BPMN 2.0 XML standard representation.
        :param xsi_prefix:
        :param bpmn_prefix:
        :param bpmndi_prefix:
        :param dc_prefix:
        :param di_prefix:
        """
        super().__init__()

        self.__xsi_prefix = xsi_prefix
        self.__bpmn_prefix = bpmn_prefix
        self.__bpmndi_prefix = bpmndi_prefix
        self.__dc_prefix = dc_prefix
        self.__di_prefix = di_prefix

        self.id_shortener = IDShortener()

    @staticmethod
    def __prefix_tag(tag: str, prefix: str | None) -> str:
        """
        Prefix a XML tag with a given prefix
        :param tag: The prefixed tag
        :param prefix: The prefix to prepend
        """
        return f"{prefix if prefix else ''}{':' if prefix else ''}{tag}"

    def __shorten_id(self, element_id: str, prefix: Optional[str] = None) -> str:
        """
        Prefix an element id with a given prefix.
        If no prefix is provided, 'bpmn' is used as default.
        :param element_id: The element id that should be prefixed
        :param prefix: The prefix to prepend
        """

        if self.id_shortener is None:
            return element_id

        return self.id_shortener.shorten_id(element_id, prefix=prefix)

    @staticmethod
    def __omit_keys(dictionary: dict, omitted_keys: list) -> dict:
        """
        Copy a dictionary while omitting keys
        :param dictionary: The dictionary that is omitted from
        :param omitted_keys: A list of keys that should be omitted
        """
        return {key: dictionary[key] for key in dictionary.keys() if key not in omitted_keys}

    @staticmethod
    def __get_flows_connected_to_element(flows: list[dict], element_id: str) -> list[dict]:
        """
        Get all flows connected to an element
        :param flows: All flows in the diagram model
        :param element_id: The id of the element to which the retrieved flows should be connected to
        """

        def is_element_connected(flow: dict) -> bool:
            return flow.get("source", {}).get("element") == element_id or flow.get("target", {}).get(
                "element") == element_id

        return list(filter(is_element_connected, flows))

    def __serialize_base_element(self, element: dict, tag: str,
                                 connected_flows: Optional[list[dict]] = None) -> ElementTree.Element:
        """
        Serialize a BPMN flow to XML
        :param element: A dictionary representing a BPMN flow element
        :param tag: The name of the tag the element should be serialized as
        :return: An Elementtree Element representing the serialized BPMN flow element
        """

        if connected_flows is None:
            connected_flows = []

        serialized_element: ElementTree.Element = ElementTree.Element(tag)
        serialized_element.set("id", self.__shorten_id(element.get("id", "")))
        serialized_element.set("name", element.get("name", ""))

        for connected_flow in connected_flows:
            source = connected_flow.get("source")
            if source and source.get("element") == element.get("id"):
                outgoing = ElementTree.Element(self.__prefix_tag("outgoing", self.__bpmn_prefix))
                outgoing.text = self.__shorten_id(connected_flow.get("id", ""))
                serialized_element.append(outgoing)

            # This is deliberately not an "else" case as otherwise connections connecting an element with itself
            # would not be correctly serialized.
            target = connected_flow.get("target")
            if target and target.get("element") == element.get("id"):
                incoming = ElementTree.Element(self.__prefix_tag("incoming", self.__bpmn_prefix))
                incoming.text = self.__shorten_id(connected_flow.get("id", ""))
                serialized_element.append(incoming)

        return serialized_element

    def __serialize_annotation(self, annotation: dict,
                               connected_flows: Optional[list[dict]] = None) -> ElementTree.Element:
        """
        Serialize a BPMN annotation object to XML
        :param annotation: A dictionary representing a BPMN annotation element
        :return: An Elementtree Element representing the serialized BPMN annotation element
        """

        tag: str = self.__prefix_tag("annotation", self.__bpmn_prefix)
        serialized_annotation: ElementTree.Element = self.__serialize_base_element(annotation, tag, connected_flows)

        return serialized_annotation

    def __serialize_call_activity(self, call_activity: dict,
                                  connected_flows: Optional[list[dict]] = None) -> ElementTree.Element:
        """
        Serialize an BPMN call activity to XML
        :param call_activity: A dictionary representing an BPMN call activity element
        :return: An Elementtree Element representing the serialized BPMN call activity element
        """
        tag: str = self.__prefix_tag("callActivity", self.__bpmn_prefix)
        serialized_call_activity: ElementTree.Element = self.__serialize_base_element(call_activity, tag,
                                                                                      connected_flows)

        return serialized_call_activity

    def __serialize_data_object(self, data_object: dict,
                                connected_flows: Optional[list[dict]] = None) -> ElementTree.Element:
        """
        Serialize a BPMN data object to XML
        :param data_object: A dictionary representing a BPMN data object element
        :return: An Elementtree Element representing the serialized BPMN data object element
        """
        tag: str = self.__prefix_tag("dataObject", self.__bpmn_prefix)
        serialized_data_object: ElementTree.Element = self.__serialize_base_element(data_object, tag, connected_flows)

        return serialized_data_object

    def __serialize_data_store(self, data_store: dict,
                               connected_flows: Optional[list[dict]] = None) -> ElementTree.Element:
        """
        Serialize a BPMN data store object to XML
        :param data_store: A dictionary representing a BPMN data store element
        :return: An Elementtree Element representing the serialized BPMN data store element
        """
        tag: str = self.__prefix_tag("dataStore", self.__bpmn_prefix)
        serialized_data_store: ElementTree.Element = self.__serialize_base_element(data_store, tag, connected_flows)

        return serialized_data_store

    def __serialize_end_event(self, end_event: dict,
                              connected_flows: Optional[list[dict]] = None) -> ElementTree.Element:
        """
        Serialize a BPMN end event object to XML
        :param end_event: A dictionary representing a BPMN end event element
        :return: An Elementtree Element representing the serialized BPMN end event element
        """
        tag: str = self.__prefix_tag("endEvent", self.__bpmn_prefix)
        serialized_end_event: ElementTree.Element = self.__serialize_base_element(end_event, tag, connected_flows)

        event_type_tag: Optional[str] = self.__end_event_definition_map[
            end_event.get("eventType", BPMNEndEventType.DEFAULT)]

        if event_type_tag:
            event_type_element: ElementTree.Element = ElementTree.Element(
                self.__prefix_tag(event_type_tag, self.__bpmn_prefix))
            event_type_element.set("id", self.__shorten_id(str(uuid.uuid4())))
            serialized_end_event.append(event_type_element)

        return serialized_end_event

    def __serialize_flow(self, flow: dict, connected_flows: Optional[list[dict]] = None) -> ElementTree.Element:
        """
        Serialize a BPMN flow to XML
        :param flow: A dictionary representing a BPMN flow element
        :return: An Elementtree Element representing the serialized BPMN flow element
        """
        tag: str = self.__prefix_tag(self.__flow_type_map.get(flow.get("flowType", BPMNFlowType.SEQUENCE), ""),
                                     self.__bpmn_prefix)
        serialized_flow: ElementTree.Element = self.__serialize_base_element(flow, tag, connected_flows)

        source: Optional[dict] = flow.get("source")
        target: Optional[dict] = flow.get("target")

        if source:
            source_element: str = self.__shorten_id(source.get("element", ""))
            serialized_flow.set("sourceRef", source_element)

        if target:
            target_element: str = self.__shorten_id(target.get("element", ""))
            serialized_flow.set("targetRef", target_element)

        return serialized_flow

    def __serialize_gateway(self, gateway: dict, connected_flows: Optional[list[dict]] = None) -> ElementTree.Element:
        """
        Serialize a BPMN gateway object to XML
        :param gateway: A dictionary representing a BPMN gateway element
        :return: An Elementtree Element representing the serialized BPMN gateway element
        """
        gateway_type_tag: str = self.__prefix_tag(
            self.__gateway_type_map[gateway.get("gatewayType", BPMNGatewayType.EXCLUSIVE)],
            self.__bpmn_prefix)
        serialized_gateway = self.__serialize_base_element(gateway, gateway_type_tag, connected_flows)

        return serialized_gateway

    def __serialize_group(self, group: dict, connected_flows: Optional[list[dict]] = None) -> ElementTree.Element:
        """
        Serialize a BPMN group to XML
        :param group: A dictionary representing a BPMN group element
        :return: An Elementtree Element representing the serialized BPMN group element
        """
        tag: str = self.__prefix_tag("group", self.__bpmn_prefix)
        serialized_group: ElementTree.Element = self.__serialize_base_element(group, tag, connected_flows)

        return serialized_group

    def __serialize_intermediate_event(self, intermediate_event: dict,
                                       connected_flows: Optional[list[dict]] = None) -> ElementTree.Element:
        """
        Serialize a BPMN intermediate event to XML
        :param intermediate_event: A dictionary representing a BPMN intermediate event element
        :return: An Elementtree Element representing the serialized BPMN intermediate event element
        """
        tag: str = self.__prefix_tag(
            self.__intermediate_event_type_map[intermediate_event.get("eventType", BPMNIntermediateEventType.DEFAULT)],
            self.__bpmn_prefix)
        serialized_intermediate_event: ElementTree.Element = self.__serialize_base_element(intermediate_event, tag,
                                                                                           connected_flows)

        event_type_tag: Optional[str] = self.__intermediate_event_definition_map[
            intermediate_event.get("eventType", BPMNIntermediateEventType.DEFAULT)]

        if event_type_tag:
            event_type_element = ElementTree.Element(self.__prefix_tag(event_type_tag, self.__bpmn_prefix))
            event_type_element.set("id", self.__shorten_id(str(uuid.uuid4())))
            serialized_intermediate_event.append(event_type_element)

        return serialized_intermediate_event

    def __serialize_pool(self, pool: dict, connected_flows: Optional[list[dict]] = None) -> ElementTree.Element:
        """
        Serialize a BPMN pool to XML
        :param pool: A dictionary representing a BPMN pool element
        :return: An Elementtree Element representing the serialized BPMN pool element
        """
        tag: str = self.__prefix_tag("laneSet", self.__bpmn_prefix)
        serialized_pool: ElementTree.Element = self.__serialize_base_element(pool, tag, connected_flows)

        return serialized_pool

    def __serialize_start_event(self, start_event: dict,
                                connected_flows: Optional[list[dict]] = None) -> ElementTree.Element:
        """
        Serialize a BPMN start event to XML
        :param start_event: A dictionary representing a BPMN start event element
        :return: An Elementtree Element representing the serialized BPMN start event element
        """
        tag: str = self.__prefix_tag("startEvent", self.__bpmn_prefix)
        serialized_start_event: ElementTree.Element = self.__serialize_base_element(start_event, tag, connected_flows)

        event_type_tag: Optional[str] = self.__start_event_definition_map[
            start_event.get("eventType", BPMNStartEventType.DEFAULT)]

        if event_type_tag:
            event_type_element = ElementTree.Element(self.__prefix_tag(event_type_tag, self.__bpmn_prefix))
            event_type_element.set("id", self.__shorten_id(str(uuid.uuid4())))
            serialized_start_event.append(event_type_element)

        return serialized_start_event

    def __serialize_subprocess(self, subprocess: dict,
                               connected_flows: Optional[list[dict]] = None) -> ElementTree.Element:
        """
        Serialize a BPMN subprocess to XML
        :param subprocess: A dictionary representing a BPMN subprocess element
        :return: An Elementtree Element representing the serialized BPMN subprocess element
        """
        tag: str = self.__prefix_tag("subprocess", self.__bpmn_prefix)
        serialized_subprocess: ElementTree.Element = self.__serialize_base_element(subprocess, tag, connected_flows)

        return serialized_subprocess

    def __serialize_swimlane(self, swimlane: dict, connected_flows: Optional[list[dict]] = None) -> ElementTree.Element:
        """
        Serialize a BPMN swimlane to XML
        :param swimlane: A dictionary representing a BPMN swimlane element
        :return: An Elementtree Element representing the serialized BPMN swimlane element
        """
        tag: str = self.__prefix_tag("lane", self.__bpmn_prefix)
        serialized_swimlane: ElementTree.Element = self.__serialize_base_element(swimlane, tag, connected_flows)

        return serialized_swimlane

    def __serialize_task(self, task: dict, connected_flows: Optional[list[dict]] = None) -> ElementTree.Element:
        """
        Serialize a BPMN task to XML
        :param task: A dictionary representing a BPMN task element
        :return: An Elementtree Element representing the serialized BPMN task element
        """
        task_tag: str = self.__prefix_tag(self.__task_type_map[task.get("taskType", BPMNTaskType.DEFAULT)],
                                          self.__bpmn_prefix)
        serialized_task: ElementTree.Element = self.__serialize_base_element(task, task_tag, connected_flows)

        return serialized_task

    def __serialize_transaction(self, transaction: dict,
                                connected_flows: Optional[list[dict]] = None) -> ElementTree.Element:
        """
        Serialize a BPMN transaction to XML
        :param transaction: A dictionary representing a BPMN transaction element
        :return: An Elementtree Element representing the serialized BPMN transaction element
        """
        tag: str = self.__prefix_tag("transaction", self.__bpmn_prefix)
        serialized_transaction: ElementTree.Element = self.__serialize_base_element(transaction, tag, connected_flows)

        return serialized_transaction

    def __serialize_element(self, element: dict, connected_flows: Optional[list[dict]] = None) -> Optional[
        ElementTree.Element]:
        """
        Serialize a BPMN element to XML

        This method selects the serializer corresponding to the given element based on its type property
        :param element: A dictionary representing a BPMN element
        :return: An Elementtree Element representing the serialized BPMN element
        """

        match element.get("type"):
            case BPMNElementType.BPMN_ANNOTATION:
                return self.__serialize_annotation(element, connected_flows)
            case BPMNElementType.BPMN_CALL_ACTIVITY:
                return self.__serialize_call_activity(element, connected_flows)
            case BPMNElementType.BPMN_DATA_OBJECT:
                return self.__serialize_data_object(element, connected_flows)
            case BPMNElementType.BPMN_DATA_STORE:
                return self.__serialize_data_store(element, connected_flows)
            case BPMNElementType.BPMN_END_EVENT:
                return self.__serialize_end_event(element, connected_flows)
            case BPMNElementType.BPMN_GATEWAY:
                return self.__serialize_gateway(element, connected_flows)
            case BPMNElementType.BPMN_GROUP:
                return self.__serialize_group(element, connected_flows)
            case BPMNElementType.BPMN_INTERMEDIATE_EVENT:
                return self.__serialize_intermediate_event(element, connected_flows)
            case BPMNElementType.BPMN_POOL:
                return self.__serialize_pool(element, connected_flows)
            case BPMNElementType.BPMN_START_EVENT:
                return self.__serialize_start_event(element, connected_flows)
            case BPMNElementType.BPMN_SUBPROCESS:
                return self.__serialize_subprocess(element, connected_flows)
            case BPMNElementType.BPMN_SWIMLANE:
                return self.__serialize_swimlane(element, connected_flows)
            case BPMNElementType.BPMN_TASK:
                return self.__serialize_task(element, connected_flows)
            case BPMNElementType.BPMN_TRANSACTION:
                return self.__serialize_transaction(element, connected_flows)

        return None

    def __serialize_shape(self, element: dict) -> ElementTree.Element:
        """
        Serialize a BPMN element to a shape
        :param element: A dictionary representing a BPMN element
        :return: An Elementtree Element representing the serialized BPMN shape
        """

        tag: str = self.__prefix_tag("BPMNShape", self.__bpmndi_prefix)
        serialized_shape: ElementTree.Element = ElementTree.Element(tag)
        serialized_shape.set("id", self.__shorten_id(str(uuid.uuid4())))
        serialized_shape.set("bpmnElement", self.__shorten_id(element.get("id", "")))

        bounds: Optional[dict] = element.get("bounds")

        if bounds:
            serialized_bounds = ElementTree.Element("dc:Bounds")
            serialized_bounds.set("x", str(bounds.get("x", 0)))
            serialized_bounds.set("y", str(bounds.get("y", 0)))
            serialized_bounds.set("width", str(bounds.get("width", 0)))
            serialized_bounds.set("height", str(bounds.get("height", 0)))
            serialized_shape.append(serialized_bounds)

        return serialized_shape

    def __serialize_edge(self, relationship: dict) -> ElementTree.Element:
        """
        Serialize a BPMN relationship to an edge
        :param relationship: A dictionary representing a BPMN relationship
        :return: An Elementtree Element representing the serialized BPMN edge
        """

        tag: str = self.__prefix_tag("BPMNEdge", self.__bpmndi_prefix)
        serialized_edge: ElementTree.Element = ElementTree.Element(tag)
        serialized_edge.set("id", self.__shorten_id(str(uuid.uuid4())))
        serialized_edge.set("bpmnElement", self.__shorten_id(relationship.get("id", "")))

        for point in relationship.get("path", []):
            serialized_waypoint: ElementTree.Element = ElementTree.Element(
                self.__prefix_tag("waypoint", self.__di_prefix))
            serialized_waypoint.set("x", str(point.get("x", 0)))
            serialized_waypoint.set("y", str(point.get("y", 0)))
            # serialized_edge.append(serialized_waypoint)

        return serialized_edge

    def __serialize_process(self, pool: dict, owned_elements: list[dict],
                            relationships: list[dict]) -> ElementTree.Element:
        """
        Serialize the process tree of a given BPMN model
        :param owned_elements: A dictionary containing the elements owned by serialized process
        :param relationships: A dictionary the relationships contained in the diagram
        :return: An Elementtree Element representing the serialized BPMN process tree
        """

        process: ElementTree.Element = ElementTree.Element(self.__prefix_tag("process", self.__bpmn_prefix))
        process.set("id", self.__shorten_id(pool.get("id", "")))
        process.set("isExecutable", "false")

        serialized_elements_by_type: dict[str, dict] = {}
        serialized_elements_by_owner: dict[str, dict] = {}

        # We first gather all diagram elements and store them in index structures indexed
        # by the element type and by their owner
        for element in owned_elements:
            connected_flows = self.__get_flows_connected_to_element(relationships, element.get("id", ""))

            serialized_element: Optional[ElementTree.Element] = self.__serialize_element(element, connected_flows)

            element_type = element.get("type", "")

            if serialized_element:
                if element_type:
                    serialized_elements_by_type[element_type] = {
                        **serialized_elements_by_type.get(element_type, {}),
                        self.__shorten_id(element.get("id", "")): serialized_element
                    }

                element_owner = self.__shorten_id(serialized_element.get("owner", ""))

                if element_owner:
                    serialized_elements_by_owner[element_owner] = {
                        **serialized_elements_by_owner.get(element_owner, {}),
                        self.__shorten_id(serialized_element.get("id", "")): serialized_element
                    }

        serialized_pool: ElementTree.Element = ElementTree.Element(self.__prefix_tag("laneSet", self.__bpmn_prefix))
        serialized_pool.set("id", self.__shorten_id(str(uuid.uuid4())))
        serialized_pool.set("name", pool.get("name", ""))

        owned_serialized_elements: list[ElementTree.Element] = list(
            chain.from_iterable([entry.values() for entry in serialized_elements_by_owner.values()]))

        for serialized_element in owned_serialized_elements:

            swimlanes = serialized_elements_by_type.get(BPMNElementType.BPMN_SWIMLANE)

            if swimlanes and swimlanes.get(serialized_element.get("id", "")):
                # We know that the serialized element is a swimlane and therefore directly
                # serialize it
                serialized_pool.append(serialized_element)

        process.append(serialized_pool)

        # Iterate over all swimlanes and add flowNodeRefs for all elements within the current lane
        for serialized_swimlane in serialized_elements_by_type.get(BPMNElementType.BPMN_SWIMLANE, {}).values():
            owned_serialized_elements = list(serialized_elements_by_owner[serialized_swimlane.get("id", "")].values())
            for serialized_element in owned_serialized_elements:
                tag: str = self.__prefix_tag("flowNodeRef", self.__bpmn_prefix)
                flow_node_ref = ElementTree.Element(tag)
                flow_node_ref.text = serialized_element.get("id")
                serialized_swimlane.append(flow_node_ref)

            serialized_pool.append(serialized_swimlane)

        # We get the dictionary of elements without pools and swimlanes
        non_bounding_elements = self.__omit_keys(serialized_elements_by_type, [BPMNElementType.BPMN_SWIMLANE])

        for serialized_element in chain.from_iterable([entry.values() for entry in non_bounding_elements.values()]):
            if serialized_element:
                process.append(serialized_element)

        return process

    def __serialize_plane(self, model: dict) -> ElementTree.Element:
        """
        Serialize the diagram tree of a given BPMN model
        :param model: A dictionary representing a BPMN diagram model
        :return: An Elementtree Element representing the serialized BPMN diagram tree
        """

        plane: ElementTree.Element = ElementTree.Element(self.__prefix_tag("BPMNPlane", self.__bpmndi_prefix))
        plane.set("id", self.__shorten_id(str(uuid.uuid4())))

        elements: Optional[dict] = model.get("elements")
        relationships: Optional[dict] = model.get("relationships")

        if elements:
            for element in elements.values():
                # We do not serialize BPMN pools directly as they are serialized based on participants
                # later in the process
                if element.get("type") != BPMNElementType.BPMN_POOL:
                    serialized_shape: ElementTree.Element = self.__serialize_shape(element)
                    plane.append(serialized_shape)

        if relationships:
            for relationship in relationships.values():
                serialized_edge: ElementTree.Element = self.__serialize_edge(relationship)
                plane.append(serialized_edge)

        return plane

    def __split_elements_by_owning_pool(self, elements: dict) -> dict:
        """
        Splits a given list of elements into a dictionary with the IDs of the root
        pool elements as keys and lists of elements contained within the respective pools
        as values. Elements that are not contained in a pool are returned as a list.
        :param elements: The list of elements that should be split
        :return: A tuple containing the dictionary of elements by owning pools and a list
        containing the elements without an owner.
        """
        elements_by_owning_pool: dict[str, list] = reduce(lambda acc, element: {
            **acc,
            (element.get("id", "")): []
        } if element.get("type") == BPMNElementType.BPMN_POOL else acc, elements.values(), {})

        unowned_elements = []

        for element in elements.values():
            if not element.get("type") == BPMNElementType.BPMN_POOL:
                owner = self.__find_root_owner_id(elements, element.get("id", ""))

                # If the owner of an element is returned as the element's own ID,
                # the element is not contained in a pool. If the owner is not a key in the
                # elementy_by_owning_pool dictionary, we assume that the element is owned by
                # another container like a group that is not located within a pool.
                if owner == element.get("id") or elements_by_owning_pool.get(owner, None) is None:
                    unowned_elements.append(element)
                else:
                    elements_by_owning_pool[owner].append(element)

        # Add all elements that are not contained in a pool to an unnamed pool
        if len(unowned_elements) > 0:
            elements_by_owning_pool[""] = unowned_elements

        return elements_by_owning_pool

    def __find_root_owner_id(self, elements: dict, current_id: str) -> str:
        """
        Find the id of the root owner of an element.
        If the element is contained within a pool, the root owner is said pool.
        If the element is not contained within another element at all, the element's own ID is returned.
        :param elements: The elements of the current diagram
        :param current_id: The element of the element whose root owner should be determined
        :return: The id of the root owner of the given current_id
        """

        current_element: Optional[dict] = elements.get(current_id)

        if current_element:
            owner_id: Optional[str] = current_element.get("owner")

            if owner_id:
                return self.__find_root_owner_id(elements, owner_id)

        return current_id

    def serialize(self, model: dict, omit_layout_info: bool = False) -> ElementTree.Element:
        """
        Serialize a BPMN diagram in Apollon's native JSON format to XML according to the BPMN 2.0 standard
        :param model: A dictionary representing a BPMN diagram model
        :param omit_layout_info: Indicates whether layouting information should be included in the diagram
        :return: An Elementtree Element representing the serialized BPMN diagram
        """

        if self.id_shortener:
            # The IDShortener is reset to ensure no prior ID mappings are cached
            self.id_shortener.reset()

        definitions: ElementTree.Element = ElementTree.Element(self.__prefix_tag("definitions", self.__bpmn_prefix))

        definitions.set("id", "Definition")
        definitions.set(f"xmlns:{self.__xsi_prefix}", "http://www.w3.org/2001/XMLSchema-instance")
        definitions.set(f"xmlns:{self.__bpmn_prefix}", "http://www.omg.org/spec/BPMN/20100524/MODEL")
        definitions.set(f"xmlns:{self.__bpmndi_prefix}", "http://www.omg.org/spec/BPMN/20100524/DI")
        definitions.set(f"xmlns:{self.__dc_prefix}", "http://www.omg.org/spec/DD/20100524/DC")
        definitions.set(f"xmlns:{self.__di_prefix}", "http://www.omg.org/spec/DD/20100524/DI")
        definitions.set("targetNamespace", "http://bpmn.io/schema/bpmn")

        diagram: ElementTree.Element = ElementTree.Element(self.__prefix_tag("BPMNDiagram", self.__bpmndi_prefix))
        serialized_plane = self.__serialize_plane(model)
        diagram.append(serialized_plane)

        elements_by_owning_pool = self.__split_elements_by_owning_pool(model.get("elements", {}))

        relationships: list[dict] = list(model.get("relationships", {}).values())

        if len(elements_by_owning_pool.keys()) > 0:

            collaboration: ElementTree.Element = ElementTree.Element(
                self.__prefix_tag("collaboration", self.__bpmn_prefix))
            collaboration.set("id", self.__shorten_id(str(uuid.uuid4())))
            definitions.append(collaboration)

            for index, pool_id in enumerate(elements_by_owning_pool):

                pool: dict = model.get("elements", {}).get(pool_id, {})
                serialized_process = self.__serialize_process(pool, elements_by_owning_pool.get(pool_id, {}),
                                                              relationships)
                definitions.append(serialized_process)

                # We append all flows to the first process as the flows coming from the Apollon
                # diagrams do not have owners assigned.
                if index == 0:
                    for relationship in relationships:
                        serialized_relationship = self.__serialize_flow(relationship)

                        # TODO: Add support for handling associations.
                        # It might make sense to either treat them similar to messages flows or to explicitly check if
                        # an element is fully contained within a pool or not an then either attach it to the pool's
                        # process or to the collaboration element.
                        match relationship.get("flowType"):
                            case BPMNFlowType.SEQUENCE:
                                serialized_process.append(serialized_relationship)
                            case BPMNFlowType.MESSAGE:
                                collaboration.append(serialized_relationship)

                participant: ElementTree.Element = ElementTree.Element(
                    self.__prefix_tag("participant", self.__bpmn_prefix))
                participant_id: str = self.__shorten_id(str(uuid.uuid4()))
                participant.set("id", participant_id)
                participant.set("processRef", self.__shorten_id(pool_id))
                participant.set("name", pool.get("name", ""))
                collaboration.append(participant)

                pool_shape = self.__serialize_shape(pool)
                pool_shape.set("bpmnElement", participant_id)
                # We add this attribute by default as Apollon diagrams currently only support horizontal pools
                pool_shape.set("isHorizontal", "true")
                serialized_plane.append(pool_shape)

            serialized_plane.set("bpmnElement", collaboration.get("id", ""))

        if not omit_layout_info:
            definitions.append(diagram)

        return definitions
