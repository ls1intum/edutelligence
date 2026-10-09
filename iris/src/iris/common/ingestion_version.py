"""Version of the lecture ingestion pipeline logic.

Bump this integer whenever a change to prompts, models, chunking, or
extraction logic means that re-running ingestion over unchanged content can
produce a genuinely different (better) result. The version is stamped into
every unit row and reported by the ingestion census, and Artemis re-ingests
quality-flagged units at most once per version: the trigger for a quality
re-run is the versioned edge (stamped version older than this constant), not
the quality level itself, which is what guarantees the re-ingestion loop
terminates instead of retrying the same content forever.
"""

INGESTION_PIPELINE_VERSION = 1
