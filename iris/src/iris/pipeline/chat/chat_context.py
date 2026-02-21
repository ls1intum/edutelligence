from enum import StrEnum, auto


class ChatContext(StrEnum):
    COURSE = auto()
    LECTURE = auto()
    EXERCISE = auto()
    TEXT_EXERCISE = auto()
