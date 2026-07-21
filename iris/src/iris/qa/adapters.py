from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

from iris.domain.retrieval.lecture.lecture_retrieval_dto import (
    LectureRetrievalDTO,
    LectureTranscriptionRetrievalDTO,
    LectureUnitPageChunkRetrievalDTO,
)
from iris.domain.search.lecture_search_dto import LectureSearchResultDTO

# pylint: disable=missing-class-docstring,invalid-name


def _lecture_data(metadata: dict):
    retrieval = metadata.get("retrieval", {})
    current = retrieval.get("currentView", {})
    pages = current.get("pages", [])
    transcripts = current.get("transcript", [])
    search = retrieval.get("search", [])

    def page(item):
        return LectureUnitPageChunkRetrievalDTO(
            uuid=str(item["uuid"]),
            course_id=42,
            course_name="Algorithms and Data Structures",
            course_description="Algorithms course",
            lecture_id=6001,
            lecture_name="Divide and Conquer",
            lecture_unit_id=int(item["lectureUnitId"]),
            lecture_unit_name=item["lectureUnitName"],
            lecture_unit_link=item.get("link", ""),
            course_language="en",
            page_number=int(item.get("pageNumber", 1)),
            display_page_number=int(item.get("pageNumber", 1)),
            page_text_content=item["text"],
            base_url="https://artemis.example.invalid",
        )

    def transcript(item):
        return LectureTranscriptionRetrievalDTO(
            uuid=str(item["uuid"]),
            course_id=42,
            course_name="Algorithms and Data Structures",
            course_description="Algorithms course",
            lecture_id=6001,
            lecture_name="Divide and Conquer",
            lecture_unit_id=int(item["lectureUnitId"]),
            lecture_unit_name=item["lectureUnitName"],
            video_link=item.get("link", ""),
            language="en",
            segment_start_time=float(item.get("startTime", 0)),
            segment_end_time=float(item.get("endTime", 999999)),
            page_number=-1,
            segment_summary=item["text"],
            segment_text=item["text"],
            base_url="https://artemis.example.invalid",
        )

    current_pages = [page(item) for item in pages]
    current_transcripts = [transcript(item) for item in transcripts]
    search_pages = [
        page(
            {
                "uuid": item["uuid"],
                "lectureUnitId": item["lectureUnitId"],
                "lectureUnitName": item["lectureUnitName"],
                "pageNumber": item.get("pageNumber", 1),
                "text": item["text"],
                "link": item.get("link", ""),
            }
        )
        for item in search
    ]
    return current_pages, current_transcripts, search_pages


class FixtureLectureRetrieval:
    metadata: dict = {}

    def __init__(self, *_args, **_kwargs):
        self.tokens = []

    def fetch_context_content(self, *_args, **_kwargs):
        pages, transcripts, _ = _lecture_data(self.metadata)
        return pages, transcripts

    def __call__(self, **_kwargs):
        pages, transcripts, search = _lecture_data(self.metadata)
        return LectureRetrievalDTO(
            lecture_unit_segments=[],
            lecture_transcriptions=transcripts,
            lecture_unit_page_chunks=search or pages,
        )


class FixtureFaqRetrieval:
    metadata: dict = {}

    def __init__(self, *_args, **_kwargs):
        self.tokens = []

    def __call__(self, **_kwargs):
        return [
            {
                "faq_id": item["id"],
                "question_title": item["question"],
                "question_answer": item["answer"],
                "course_id": 42,
                "course_name": "Algorithms and Data Structures",
                "base_url": "https://artemis.example.invalid",
                "link": item.get("link", ""),
            }
            for item in self.metadata.get("retrieval", {}).get("faqs", [])
        ]


class FixtureMemiris:
    metadata: dict = {}

    def __init__(self, *_args, **_kwargs):
        pass

    def has_memories(self):
        return bool(self.metadata.get("memories"))

    def create_tool_memory_search(self, _storage):
        metadata = self.metadata

        def memiris_search_for_memories(query: str = "") -> str:
            """Search the scenario's synthetic student memories."""
            del query
            return "\n".join(item["content"] for item in metadata.get("memories", []))

        return memiris_search_for_memories

    def create_tool_find_similar_memories(self, _storage):
        metadata = self.metadata

        def memiris_find_similar_memories(query: str = "") -> str:
            """Find memories similar to the scenario's synthetic chat context."""
            del query
            return "\n".join(item["content"] for item in metadata.get("memories", []))

        return memiris_find_similar_memories

    def create_memories_in_separate_thread(self, *_args, **_kwargs):
        # The product enables background learning when the user has Memiris
        # enabled. QA must preserve read/tool behavior while performing no
        # external write and starting no background thread.
        return None


class FixtureVectorDatabase:
    def __init__(self):
        self.client = SimpleNamespace()


class FixtureGlobalRetriever:
    metadata: dict = {}

    def __init__(self, *_args, **_kwargs):
        pass

    def _sources(self):
        return [
            LectureSearchResultDTO.model_validate(
                {
                    "course": {"id": 42, "name": item["course"]},
                    "lecture": {"id": 6001, "name": item["lecture"]},
                    "lectureUnit": {
                        "id": 7001,
                        "name": item["lecture"],
                        "link": "/courses/42/lectures/6001",
                        "pageNumber": item.get("page", 1),
                        "sourceType": "LECTURE_UNIT_PAGE",
                    },
                    "snippet": item["snippet"],
                }
            )
            for item in self.metadata.get("sources", [])
        ]

    def search(self, **_kwargs):
        return self._sources()

    def search_with_vector_override(self, **_kwargs):
        return self._sources()


class ScenarioAdapters:
    """Narrow, process-local replacements for external retrieval and callbacks."""

    def __init__(self, qa_metadata: dict):
        self.metadata = qa_metadata
        self.stack = ExitStack()

    def __enter__(self):
        FixtureLectureRetrieval.metadata = self.metadata
        FixtureFaqRetrieval.metadata = self.metadata
        FixtureMemiris.metadata = self.metadata
        FixtureGlobalRetriever.metadata = self.metadata
        retrieval = self.metadata.get("retrieval", {})
        lecture_available = bool(retrieval.get("lectureAvailable"))
        faq_available = bool(retrieval.get("faqAvailable"))
        synthetic_now = datetime.fromisoformat(
            str(self.metadata["syntheticNow"]).replace("Z", "+00:00")
        ).astimezone(timezone.utc)
        formatted_now = synthetic_now.strftime("%Y-%m-%d %H:%M:%S")

        class FrozenDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                if tz is None:
                    return synthetic_now.replace(tzinfo=None)
                return synthetic_now.astimezone(tz)

        patches = {
            "iris.pipeline.abstract_agent_pipeline.VectorDatabase": FixtureVectorDatabase,
            "iris.pipeline.abstract_agent_pipeline.MemirisWrapper": FixtureMemiris,
            "iris.pipeline.chat.chat_pipeline.LectureRetrieval": FixtureLectureRetrieval,
            "iris.tools.chat_tool_providers.LectureRetrieval": FixtureLectureRetrieval,
            "iris.tools.chat_tool_providers.FaqRetrieval": FixtureFaqRetrieval,
            "iris.pipeline.tutor_suggestion_pipeline.LectureRetrieval": FixtureLectureRetrieval,
            "iris.pipeline.tutor_suggestion_pipeline.FaqRetrieval": FixtureFaqRetrieval,
            "iris.pipeline.autonomous_tutor_pipeline.LectureRetrieval": FixtureLectureRetrieval,
            "iris.pipeline.autonomous_tutor_pipeline.FaqRetrieval": FixtureFaqRetrieval,
            "iris.pipeline.global_search_pipeline.LectureGlobalSearchRetrieval": FixtureGlobalRetriever,
            "iris.pipeline.chat.chat_pipeline.datetime": FrozenDateTime,
            "iris.pipeline.tutor_suggestion_pipeline.get_current_utc_datetime_string": lambda: formatted_now,
            "iris.pipeline.autonomous_tutor_pipeline.get_current_utc_datetime_string": lambda: formatted_now,
            "iris.pipeline.shared.utils.datetime": FrozenDateTime,
            "iris.tools.additional_exercise_details.datetime": FrozenDateTime,
            "iris.tools.exercise_list.datetime": FrozenDateTime,
        }
        for target, replacement in patches.items():
            self.stack.enter_context(patch(target, replacement))
        for target in (
            "iris.pipeline.chat.chat_pipeline.should_allow_lecture_tool",
            "iris.pipeline.tutor_suggestion_pipeline.should_allow_lecture_tool",
            "iris.pipeline.autonomous_tutor_pipeline.should_allow_lecture_tool",
        ):
            self.stack.enter_context(patch(target, return_value=lecture_available))
        for target in (
            "iris.pipeline.chat.chat_pipeline.should_allow_faq_tool",
            "iris.pipeline.tutor_suggestion_pipeline.should_allow_faq_tool",
            "iris.pipeline.autonomous_tutor_pipeline.should_allow_faq_tool",
        ):
            self.stack.enter_context(patch(target, return_value=faq_available))

        pages, transcripts, search = _lecture_data(self.metadata)
        content = (
            "\n".join(
                [item.page_text_content for item in (*pages, *search)]
                + [item.segment_text for item in transcripts]
            )
            or None
        )
        mcq_value = (
            content,
            (
                [
                    {
                        "lecture_unit_id": 7001,
                        "lecture_name": "Divide and Conquer",
                        "unit_name": "Merge Sort Recurrence",
                        "first_page": "8",
                    }
                ]
                if content
                else []
            ),
        )
        for target in (
            "iris.pipeline.chat.mcq_chat_mixin.retrieve_lecture_content_for_mcq",
            "iris.tools.chat_tool_providers.retrieve_lecture_content_for_mcq",
        ):
            self.stack.enter_context(patch(target, return_value=mcq_value))
        return self

    def __exit__(self, exc_type, exc, traceback):
        return self.stack.__exit__(exc_type, exc, traceback)
