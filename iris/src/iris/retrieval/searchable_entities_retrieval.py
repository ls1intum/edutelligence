from weaviate import WeaviateClient
from weaviate.classes.query import Filter, MetadataQuery

from iris.common.logging_config import get_logger
from iris.domain.search.lecture_search_dto import (
    AccessContext,
    CourseInfo,
    GlobalSearchSourceDTO,
)
from iris.llm import LlmRequestHandler
from iris.llm.llm_configuration import resolve_model
from iris.vector_database.searchable_entities_schema import (
    EntityType,
    FaqState,
    SearchableEntitiesSchema,
)

logger = get_logger(__name__)


class SearchableEntitiesRetrieval:
    """Queries the Artemis-managed ``SearchableEntities`` Weaviate collection.

    Searches exercises, FAQs, exams, and channels using the same access control rules
    that Florian's GlobalSearchResource applies — expressed as opaque course-ID sets
    passed in AccessContext. Pyris has no business logic here: it only applies the
    filters it receives.

    Lecture and lecture_unit rows in this collection are intentionally excluded because
    the LectureGlobalSearchRetrieval pipeline handles them with richer semantic search
    (segment-level content, video transcriptions, HyDE).
    """

    def __init__(
        self,
        client: WeaviateClient,
        local: bool = False,
        collection_name: str | None = None,
    ):
        resolved = collection_name or SearchableEntitiesSchema.COLLECTION_NAME.value
        self.collection = client.collections.get(resolved)

        # Detect whether Artemis indexed vectors into this collection.
        # vectorizer "none" + no stored vectors → alpha=0 (pure BM25, model-agnostic).
        # vectorizer "text2vec-openai" with the same qwen3-embedding model → alpha=0.7 (hybrid).
        try:
            config = self.collection.config.get(simple=False)
            default_vec = (config.vector_config or {}).get("default")
            vectorizer = str(
                getattr(getattr(default_vec, "vectorizer", None), "vectorizer", "none")
            ).lower()
            has_vectors = "none" not in vectorizer
        except Exception:
            has_vectors = False
        self._alpha = 0.7 if has_vectors else 0.0
        logger.info(
            "[SearchableEntities] vectorizer=%s → alpha=%.1f (%s)",
            vectorizer if has_vectors else "none",
            self._alpha,
            (
                "hybrid (vector + BM25, same Qwen3 model as Pyris)"
                if has_vectors
                else "BM25-only (no vectors stored)"
            ),
        )

        if has_vectors:
            embedding_model = resolve_model(
                "global_search_pipeline", "default", "embedding", local=local
            )
            self.llm_embedding = LlmRequestHandler(model_id=embedding_model)
        else:
            self.llm_embedding = None

    def search(
        self,
        query: str,
        limit: int,
        access_context: AccessContext | None,
        vector_text: str | None = None,
    ) -> list[GlobalSearchSourceDTO]:
        """Hybrid search across exercises, FAQs, exams, and channels.

        :param query: Free-text query.
        :param limit: Maximum results to return (split across entity types).
        :param access_context: Resolved course-ID sets from Artemis. None means admin —
                               run without any filter. Non-None with empty lists means no
                               accessible courses — return nothing.
        :return: List of unified source DTOs, scored and sorted by relevance.
        """
        if access_context is None:
            logger.info(
                "[SearchableEntities] admin user — running without course filter"
            )
            return self._search_no_filter(query, limit, vector_text=vector_text)

        logger.info(
            "[access-ctx] all=%s | editor=%s | ta=%s | student=%s | staff=%s",
            access_context.course_ids,
            access_context.editor_course_ids,
            access_context.ta_course_ids,
            access_context.student_course_ids,
            access_context.staff_course_ids,
        )

        if access_context.is_empty():
            logger.info("[SearchableEntities] access context is empty — skipping query")
            return []

        combined_filter = self._build_access_filter(access_context)
        if combined_filter is None:
            logger.info(
                "[SearchableEntities] no accessible entities for this user — skipping query"
            )
            return []

        embed_text = vector_text if vector_text else query
        vector = self.llm_embedding.embed(embed_text) if self.llm_embedding else None
        try:
            results = self.collection.query.hybrid(
                query=query,
                alpha=self._alpha,
                vector=vector,
                limit=limit,
                filters=combined_filter,
                return_metadata=MetadataQuery(score=True),
            ).objects
        except Exception:
            logger.warning("[SearchableEntities] Weaviate query failed", exc_info=True)
            return []

        scored: list[tuple[float, GlobalSearchSourceDTO]] = []
        for obj in results:
            dto = self._to_dto(obj.properties)
            if dto is not None:
                score = (
                    obj.metadata.score
                    if obj.metadata and obj.metadata.score is not None
                    else 0.0
                )
                dto.score = score
                scored.append((score, dto))

        scored.sort(key=lambda x: x[0], reverse=True)
        final = [dto for _, dto in scored]

        # Log per-type breakdown with scores
        by_type: dict[str, list[str]] = {}
        for dto in final:
            by_type.setdefault(dto.source_type, []).append(
                f"{dto.title}({dto.score:.3f})"
            )
        for entity_type, titles in by_type.items():
            logger.info(
                "[SearchableEntities] type=%s  hits=%d  titles=%s",
                entity_type,
                len(titles),
                titles,
            )
        if not final:
            logger.info("[SearchableEntities] no results found")
        return final

    def _search_no_filter(
        self, query: str, limit: int, vector_text: str | None = None
    ) -> list[GlobalSearchSourceDTO]:
        """Admin path — query SearchableEntities with no course filter, but exclude lectures
        (handled by LectureGlobalSearchRetrieval with richer content)."""
        type_filter = (
            self._type_eq(EntityType.EXERCISE)
            | self._type_eq(EntityType.FAQ)
            | self._type_eq(EntityType.EXAM)
            | self._type_eq(EntityType.CHANNEL)
        )
        embed_text = vector_text if vector_text else query
        vector = self.llm_embedding.embed(embed_text) if self.llm_embedding else None
        try:
            results = self.collection.query.hybrid(
                query=query,
                alpha=self._alpha,
                vector=vector,
                limit=limit,
                filters=type_filter,
                return_metadata=MetadataQuery(score=True),
            ).objects
        except Exception as e:
            if "could not find class" in str(e):
                logger.info(
                    "[SearchableEntities] collection not found in Weaviate — "
                    "this is expected locally (Artemis indexes this collection only on shared servers)"
                )
            else:
                logger.warning("[SearchableEntities] admin query failed", exc_info=True)
            return []
        scored = []
        for obj in results:
            dto = self._to_dto(obj.properties)
            if dto is not None:
                score = (
                    obj.metadata.score
                    if obj.metadata and obj.metadata.score is not None
                    else 0.0
                )
                dto.score = score
                scored.append((score, dto))
        scored.sort(key=lambda x: x[0], reverse=True)
        final = [dto for _, dto in scored]
        by_type: dict[str, list[str]] = {}
        for dto in final:
            by_type.setdefault(dto.source_type, []).append(
                f"{dto.title}({dto.score:.3f})"
            )
        for entity_type, titles in by_type.items():
            logger.info(
                "[SearchableEntities/admin] type=%s  hits=%d  titles=%s",
                entity_type,
                len(titles),
                titles,
            )
        return final

    def _build_access_filter(self, ctx: AccessContext) -> Filter | None:
        """Builds a compound Weaviate filter that mirrors GlobalSearchResource's per-type disjuncts."""
        disjuncts: list[Filter] = []

        exercise_filter = self._exercise_filter(ctx)
        if exercise_filter is not None:
            disjuncts.append(exercise_filter)

        faq_filter = self._faq_filter(ctx)
        if faq_filter is not None:
            disjuncts.append(faq_filter)

        exam_filter = self._exam_filter(ctx)
        if exam_filter is not None:
            disjuncts.append(exam_filter)

        channel_filter = self._channel_filter(ctx)
        if channel_filter is not None:
            disjuncts.append(channel_filter)

        if not disjuncts:
            return None
        if len(disjuncts) == 1:
            return disjuncts[0]
        combined = disjuncts[0]
        for f in disjuncts[1:]:
            combined = combined | f
        return combined

    def _type_eq(self, type_value: str) -> Filter:
        return Filter.by_property(SearchableEntitiesSchema.TYPE.value).equal(type_value)

    def _course_in(self, course_ids: list[int]) -> Filter:
        return Filter.by_property(
            SearchableEntitiesSchema.COURSE_ID.value
        ).contains_any(course_ids)

    def _exercise_filter(self, ctx: AccessContext) -> Filter | None:
        """
        SYNC[global-search-access-filters]: mirrors GlobalSearchResource.buildExerciseDisjunct
        update both when exercise visibility rules change.
        - Editors: all exercises in their courses
        - TAs: all exercises in their courses
        - Students: enrolled courses where release_date <= now (or no release date)
        """
        type_f = self._type_eq(EntityType.EXERCISE)
        sub: list[Filter] = []

        staff_ids = ctx.editor_course_ids + ctx.ta_course_ids
        if staff_ids:
            sub.append(self._course_in(staff_ids))

        if ctx.student_course_ids:
            now = ctx.effective_now()
            released = Filter.by_property(
                SearchableEntitiesSchema.RELEASE_DATE.value
            ).is_none(True) | Filter.by_property(
                SearchableEntitiesSchema.RELEASE_DATE.value
            ).less_or_equal(
                now
            )
            sub.append(self._course_in(ctx.student_course_ids) & released)

        if not sub:
            return None
        course_filter = sub[0]
        for f in sub[1:]:
            course_filter = course_filter | f
        return type_f & course_filter

    def _faq_filter(self, ctx: AccessContext) -> Filter | None:
        """
        SYNC[global-search-access-filters]: mirrors GlobalSearchResource.buildFaqDisjunct
        update both when FAQ visibility rules change.
        - Staff: all FAQ states in their courses
        - Students: only ACCEPTED FAQs in their courses
        """
        type_f = self._type_eq(EntityType.FAQ)
        sub: list[Filter] = []

        if ctx.staff_course_ids:
            sub.append(self._course_in(ctx.staff_course_ids))

        if ctx.student_course_ids:
            accepted = Filter.by_property(
                SearchableEntitiesSchema.FAQ_STATE.value
            ).equal(FaqState.ACCEPTED)
            sub.append(self._course_in(ctx.student_course_ids) & accepted)

        if not sub:
            return None
        course_filter = sub[0]
        for f in sub[1:]:
            course_filter = course_filter | f
        return type_f & course_filter

    def _exam_filter(self, ctx: AccessContext) -> Filter | None:
        """
        SYNC[global-search-access-filters]: mirrors GlobalSearchResource.buildExamDisjunct
        update both when exam visibility rules change.
        - Staff: all exams in their courses
        - Students: enrolled courses where visible_date <= now
        """
        type_f = self._type_eq(EntityType.EXAM)
        sub: list[Filter] = []

        if ctx.staff_course_ids:
            sub.append(self._course_in(ctx.staff_course_ids))

        if ctx.student_course_ids:
            now = ctx.effective_now()
            visible = Filter.by_property(
                SearchableEntitiesSchema.VISIBLE_DATE.value
            ).is_none(True) | Filter.by_property(
                SearchableEntitiesSchema.VISIBLE_DATE.value
            ).less_or_equal(
                now
            )
            sub.append(self._course_in(ctx.student_course_ids) & visible)

        if not sub:
            return None
        course_filter = sub[0]
        for f in sub[1:]:
            course_filter = course_filter | f
        return type_f & course_filter

    def _channel_filter(self, ctx: AccessContext) -> Filter | None:
        """
        SYNC[global-search-access-filters]: mirrors GlobalSearchResource.buildChannelDisjunct
        update both when channel visibility rules change.
        - All accessible courses, but only public or course-wide channels
        """
        if not ctx.course_ids:
            return None
        type_f = self._type_eq(EntityType.CHANNEL)
        course_f = self._course_in(ctx.course_ids)
        visible = Filter.by_property(
            SearchableEntitiesSchema.CHANNEL_IS_PUBLIC.value
        ).equal(True) | Filter.by_property(
            SearchableEntitiesSchema.CHANNEL_IS_COURSE_WIDE.value
        ).equal(
            True
        )
        return type_f & course_f & visible

    def _to_dto(self, props: dict) -> GlobalSearchSourceDTO | None:
        entity_type = props.get(SearchableEntitiesSchema.TYPE.value)
        entity_id = props.get(SearchableEntitiesSchema.ENTITY_ID.value)
        course_id = props.get(SearchableEntitiesSchema.COURSE_ID.value)
        title = props.get(SearchableEntitiesSchema.TITLE.value)

        if entity_type is None or entity_id is None or course_id is None or not title:
            return None

        course_name = (
            ""  # enriched with current Artemis title after the final RRF merge
        )
        description = props.get(SearchableEntitiesSchema.DESCRIPTION.value)
        snippet = description.strip() if description and description.strip() else title
        exercise_type = props.get(SearchableEntitiesSchema.EXERCISE_TYPE.value)

        return GlobalSearchSourceDTO(
            sourceType=entity_type,
            entityId=int(entity_id),
            course=CourseInfo(id=int(course_id), name=course_name),
            title=title,
            snippet=snippet,
            exerciseType=exercise_type,
        )
