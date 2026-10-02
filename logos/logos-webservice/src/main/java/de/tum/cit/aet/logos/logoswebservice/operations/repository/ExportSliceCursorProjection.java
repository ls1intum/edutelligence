package de.tum.cit.aet.logos.logoswebservice.operations.repository;

import java.time.Instant;

/**
 * One keyset key of the export's capped slice: timestamp and id, newest first.
 * Preparation captures the ordered keys so the download can stream exactly
 * those rows after the short snapshot ends; the last key is also the
 * continuation cursor when the window outruns the cap.
 */
public interface ExportSliceCursorProjection {
    Instant getTimestampRequest();
    Integer getId();
}
