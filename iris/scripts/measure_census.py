"""Time the per-course ingestion census against a local Weaviate.

The census confirms every row it reports against the object store, one read per row.
Artemis gives the endpoint 60 seconds. This script seeds a synthetic course of
50 PDF units (100 pages and 2 page chunks per page, plus 1 segment per page) and
300 transcript rows, then times the census sequentially and with the configured
parallelism. The acceptance bar is: parallel run under 30 seconds, half of the
Artemis timeout.

Run it from the ``iris`` directory against a throwaway local Weaviate:

    APPLICATION_YML_PATH=application.yml poetry run python scripts/measure_census.py

It refuses to run against a Weaviate host that is not local, because it writes data.
All rows it writes carry a dedicated course id and base URL and are deleted again
unless ``--keep`` is given. The page chunks, segments and transcripts use small random
vectors (``--vector-dim``); a local Weaviate that already holds vectors of another
dimension in these collections needs a matching value.
"""

import argparse
import json
import platform
import random
import statistics
import sys
import time

from weaviate.classes.query import Filter

from iris.config import settings
from iris.vector_database.database import VectorDatabase
from iris.vector_database.lecture_transcription_schema import (
    LectureTranscriptionSchema,
)
from iris.vector_database.lecture_unit_page_chunk_schema import (
    LectureUnitPageChunkSchema,
)
from iris.vector_database.lecture_unit_schema import LectureUnitSchema
from iris.vector_database.lecture_unit_segment_schema import (
    LectureUnitSegmentSchema,
)
from iris.web.routers.ingestion_census import get_course_ingestion_census

# A course id and base URL no real installation uses, so cleanup can never touch real data.
COURSE_ID = 987_654_321
BASE_URL = "http://census-measurement.invalid"
LECTURE_ID = 1
FIRST_PDF_UNIT_ID = 1_000
FIRST_VIDEO_UNIT_ID = 5_000
ACCEPTANCE_SECONDS = 30.0
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _course_filter(schema):
    return Filter.by_property(schema.BASE_URL.value).equal(
        BASE_URL
    ) & Filter.by_property(schema.COURSE_ID.value).equal(COURSE_ID)


def _delete_course(db: VectorDatabase) -> None:
    for collection, schema in (
        (db.lectures, LectureUnitPageChunkSchema),
        (db.transcriptions, LectureTranscriptionSchema),
        (db.lecture_segments, LectureUnitSegmentSchema),
        (db.lecture_units, LectureUnitSchema),
    ):
        collection.data.delete_many(where=_course_filter(schema))


def _insert(collection, rows) -> None:
    with collection.batch.dynamic() as batch:
        for properties, vector in rows:
            batch.add_object(properties=properties, vector=vector)
    if collection.batch.failed_objects:
        failed = collection.batch.failed_objects
        reason = getattr(failed[0], "message", failed[0])
        raise RuntimeError(f"{len(failed)} objects were not written: {reason}")


def _seed(db: VectorDatabase, args) -> dict:
    # Synthetic test vectors, not security material.
    rng = random.Random(0)  # nosec B311

    def vector():
        return [rng.random() for _ in range(args.vector_dim)]

    unit_rows, chunk_rows, segment_rows, transcript_rows = [], [], [], []
    for index in range(args.pdf_units):
        unit_id = FIRST_PDF_UNIT_ID + index
        run_id = f"measure-run-{unit_id}"
        unit_rows.append(
            (
                {
                    LectureUnitSchema.COURSE_ID.value: COURSE_ID,
                    LectureUnitSchema.BASE_URL.value: BASE_URL,
                    LectureUnitSchema.LECTURE_ID.value: LECTURE_ID,
                    LectureUnitSchema.LECTURE_UNIT_ID.value: unit_id,
                    LectureUnitSchema.CONTENT_FINGERPRINT.value: f"v1:measure-{unit_id}",
                    LectureUnitSchema.EXPECTED_CHUNK_COUNTS.value: json.dumps(
                        {"pages": args.pages * args.chunks_per_page}
                    ),
                    LectureUnitSchema.COURSE_LANGUAGE.value: "en",
                },
                vector(),
            )
        )
        for page in range(1, args.pages + 1):
            for chunk_index in range(args.chunks_per_page):
                chunk_rows.append(
                    (
                        {
                            LectureUnitPageChunkSchema.COURSE_ID.value: COURSE_ID,
                            LectureUnitPageChunkSchema.BASE_URL.value: BASE_URL,
                            LectureUnitPageChunkSchema.LECTURE_ID.value: LECTURE_ID,
                            LectureUnitPageChunkSchema.LECTURE_UNIT_ID.value: unit_id,
                            LectureUnitPageChunkSchema.PAGE_NUMBER.value: page,
                            LectureUnitPageChunkSchema.DISPLAY_PAGE_NUMBER.value: page,
                            LectureUnitPageChunkSchema.PAGE_VERSION.value: 1,
                            LectureUnitPageChunkSchema.INGESTION_RUN_ID.value: run_id,
                            LectureUnitPageChunkSchema.PAGE_TEXT_CONTENT.value: (
                                f"synthetic page {page} chunk {chunk_index}"
                            ),
                        },
                        vector(),
                    )
                )
            segment_rows.append(
                (
                    {
                        LectureUnitSegmentSchema.COURSE_ID.value: COURSE_ID,
                        LectureUnitSegmentSchema.BASE_URL.value: BASE_URL,
                        LectureUnitSegmentSchema.LECTURE_ID.value: LECTURE_ID,
                        LectureUnitSegmentSchema.LECTURE_UNIT_ID.value: unit_id,
                        LectureUnitSegmentSchema.PAGE_NUMBER.value: page,
                        LectureUnitSegmentSchema.DISPLAY_PAGE_NUMBER.value: page,
                        LectureUnitSegmentSchema.SEGMENT_SUMMARY.value: (
                            f"synthetic summary of page {page}"
                        ),
                    },
                    vector(),
                )
            )
    per_video_unit = args.transcript_rows // args.video_units
    for index in range(args.video_units):
        unit_id = FIRST_VIDEO_UNIT_ID + index
        for segment in range(per_video_unit):
            transcript_rows.append(
                (
                    {
                        LectureTranscriptionSchema.COURSE_ID.value: COURSE_ID,
                        LectureTranscriptionSchema.BASE_URL.value: BASE_URL,
                        LectureTranscriptionSchema.LECTURE_ID.value: LECTURE_ID,
                        LectureTranscriptionSchema.LECTURE_UNIT_ID.value: unit_id,
                        LectureTranscriptionSchema.INGESTION_RUN_ID.value: (
                            f"measure-run-{unit_id}"
                        ),
                        LectureTranscriptionSchema.SEGMENT_START_TIME.value: float(
                            segment * 10
                        ),
                        LectureTranscriptionSchema.SEGMENT_END_TIME.value: float(
                            segment * 10 + 10
                        ),
                        LectureTranscriptionSchema.PAGE_NUMBER.value: 1,
                        LectureTranscriptionSchema.SEGMENT_TEXT.value: (
                            f"synthetic transcript segment {segment}"
                        ),
                    },
                    vector(),
                )
            )
    _insert(db.lecture_units, unit_rows)
    _insert(db.lectures, chunk_rows)
    _insert(db.lecture_segments, segment_rows)
    _insert(db.transcriptions, transcript_rows)
    return {
        "unit_rows": len(unit_rows),
        "page_chunks": len(chunk_rows),
        "segments": len(segment_rows),
        "transcript_rows": len(transcript_rows),
    }


def _mean_read_latency_ms(db: VectorDatabase, samples: int) -> float:
    """Mean latency of one object-store read, the unit the census pays per row."""
    objects = db.lectures.query.fetch_objects(
        filters=_course_filter(LectureUnitPageChunkSchema), limit=samples
    ).objects
    timings = []
    for stored_object in objects:
        started = time.perf_counter()
        db.lectures.query.fetch_object_by_id(stored_object.uuid)
        timings.append((time.perf_counter() - started) * 1000)
    return statistics.mean(timings)


def _time_census(concurrency: int, repeats: int) -> tuple[list[float], dict]:
    settings.lecture_ingestion.census_confirm_concurrency = concurrency
    durations, census = [], None
    for _ in range(repeats):
        started = time.perf_counter()
        census = get_course_ingestion_census(COURSE_ID, base_url=BASE_URL)
        durations.append(time.perf_counter() - started)
    return durations, census.model_dump(by_alias=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", maxsplit=1)[0])
    parser.add_argument("--pdf-units", type=int, default=50)
    parser.add_argument("--pages", type=int, default=100)
    parser.add_argument("--chunks-per-page", type=int, default=2)
    parser.add_argument("--video-units", type=int, default=5)
    parser.add_argument("--transcript-rows", type=int, default=300)
    parser.add_argument("--parallel", type=int, default=16)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--latency-samples", type=int, default=200)
    parser.add_argument("--vector-dim", type=int, default=8)
    parser.add_argument("--keep", action="store_true", help="keep the seeded rows")
    parser.add_argument("--output", help="write the result as JSON to this path")
    args = parser.parse_args()

    if settings.weaviate.host.lower() not in LOCAL_HOSTS:
        print(
            f"Refusing to seed {settings.weaviate.host}: only a local Weaviate is allowed."
        )
        return 2

    db = VectorDatabase()
    meta = db.client.get_meta()
    _delete_course(db)
    try:
        started = time.perf_counter()
        data_size = _seed(db, args)
        seed_seconds = time.perf_counter() - started
        latency_ms = _mean_read_latency_ms(db, args.latency_samples)
        sequential, sequential_census = _time_census(1, args.repeats)
        parallel, parallel_census = _time_census(args.parallel, args.repeats)
    finally:
        if not args.keep:
            _delete_course(db)

    result = {
        "environment": {
            "weaviate_version": meta.get("version"),
            "weaviate_host": f"{settings.weaviate.host}:{settings.weaviate.port}",
            "python": platform.python_version(),
            "machine": platform.platform(),
        },
        "data_size": data_size,
        "seed_seconds": round(seed_seconds, 1),
        "mean_read_latency_ms": round(latency_ms, 2),
        "sequential_seconds": [round(value, 2) for value in sequential],
        "parallel_concurrency": args.parallel,
        "parallel_seconds": [round(value, 2) for value in parallel],
        "same_result": sequential_census == parallel_census,
    }
    parallel_mean = statistics.mean(parallel)
    result["acceptance"] = {
        "limit_seconds": ACCEPTANCE_SECONDS,
        "parallel_mean_seconds": round(parallel_mean, 2),
        "passed": parallel_mean < ACCEPTANCE_SECONDS and result["same_result"],
    }
    print(json.dumps(result, indent=2))
    if args.output:
        with open(args.output, "w", encoding="utf-8") as output:
            json.dump(result, output, indent=2)
    return 0 if result["acceptance"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
