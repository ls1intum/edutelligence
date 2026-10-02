package de.tum.cit.aet.logos.logoswebservice.operations.repository;

import java.time.Instant;

/**
 * The tail of the export's capped slice: the row a continued export starts
 * from. Timestamp and id are the keyset the export walks newest first, so
 * they are all the continuation needs — the row's content stays in the
 * database, where the next slice will read it.
 */
public interface ExportSliceCursorProjection {
    Instant getTimestampRequest();
    Integer getId();
}
