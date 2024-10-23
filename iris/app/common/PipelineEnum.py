from enum import Enum


class PipelineEnum(str, Enum):
    IRIS_CODE_FEEDBACK = "IRIS_CODE_FEEDBACK"
    IRIS_CHAT_COURSE_MESSAGE = "IRIS_CHAT_COURSE_MESSAGE"
    IRIS_CHAT_EXERCISE_MESSAGE = "IRIS_CHAT_EXERCISE_MESSAGE"
    IRIS_INTERACTION_SUGGESTION = "IRIS_INTERACTION_SUGGESTION"
    IRIS_CHAT_LECTURE_MESSAGE = "IRIS_CHAT_LECTURE_MESSAGE"
    IRIS_COMPETENCY_GENERATION = "IRIS_COMPETENCY_GENERATION"
    IRIS_CITATION_PIPELINE = "IRIS_CITATION_PIPELINE"
    IRIS_RERANKER_PIPELINE = "IRIS_RERANKER_PIPELINE"
    IRIS_SUMMARY_PIPELINE = "IRIS_SUMMARY_PIPELINE"
    IRIS_LECTURE_RETRIEVAL_PIPELINE = "IRIS_LECTURE_RETRIEVAL_PIPELINE"
    IRIS_LECTURE_INGESTION = "IRIS_LECTURE_INGESTION"
    NOT_SET = "NOT_SET"
