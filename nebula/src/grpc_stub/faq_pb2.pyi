from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class FAQ(_message.Message):
    __slots__ = ("question_title", "question_answer")
    QUESTION_TITLE_FIELD_NUMBER: _ClassVar[int]
    QUESTION_ANSWER_FIELD_NUMBER: _ClassVar[int]
    question_title: str
    question_answer: str
    def __init__(self, question_title: _Optional[str] = ..., question_answer: _Optional[str] = ...) -> None: ...

class FaqRewritingRequest(_message.Message):
    __slots__ = ("faqs", "input_text")
    FAQS_FIELD_NUMBER: _ClassVar[int]
    INPUT_TEXT_FIELD_NUMBER: _ClassVar[int]
    faqs: _containers.RepeatedCompositeFieldContainer[FAQ]
    input_text: str
    def __init__(self, faqs: _Optional[_Iterable[_Union[FAQ, _Mapping]]] = ..., input_text: _Optional[str] = ...) -> None: ...

class FaqRewritingResponse(_message.Message):
    __slots__ = ("result",)
    RESULT_FIELD_NUMBER: _ClassVar[int]
    result: str
    def __init__(self, result: _Optional[str] = ...) -> None: ...
