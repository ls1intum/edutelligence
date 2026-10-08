package de.tum.cit.aet.logos.logoswebservice.operations;

import java.io.ByteArrayOutputStream;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.stream.Collectors;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import de.tum.cit.aet.logos.logoswebservice.identity.repository.TeamRepository;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.ExportSliceCursorProjection;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.LogEntryRepository;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.LogExportProjection;
import de.tum.cit.aet.logos.logoswebservice.operations.service.RequestLogService;
import de.tum.cit.aet.logos.logoswebservice.operations.service.TeamActivityService;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

/**
 * A late commit between prepare and stream must not enlarge a capped export.
 *
 * Preparation freezes the capped id set (A, B). A row D whose timestamp falls
 * between A and B can commit before streaming; the download still emits only
 * the prepared ids, and the advertised count stays equal to the file.
 */
class TeamActivityExportSliceMembershipTest {

    @Test
    void aCommitBetweenPrepareAndStreamDoesNotEnlargeTheCappedSlice() throws Exception {
        LogEntryRepository repository = mock(LogEntryRepository.class);
        RequestLogService requestLogService = mock(RequestLogService.class);
        TeamRepository teamRepository = mock(TeamRepository.class);

        Instant tsA = Instant.parse("2026-10-01T12:00:02Z");
        Instant tsD = Instant.parse("2026-10-01T12:00:01.500Z");
        Instant tsB = Instant.parse("2026-10-01T12:00:01Z");
        Instant tsC = Instant.parse("2026-10-01T12:00:00Z");

        int idA = 101;
        int idD = 104;
        int idB = 102;
        int idC = 103;

        // Window holds A/B/C (and will grow to include D). Cap is two: prepare
        // freezes A then B. D commits after prepare with a timestamp between
        // them — the old inclusive-tail walk would have emitted A/D/B.
        when(repository.countTracesForExport(anyInt(), any(), any(), any(), any(), any()))
            .thenReturn(3L);
        when(repository.findExportSliceKeys(anyInt(), any(), any(), any(), any(), any(), anyInt()))
            .thenReturn(List.of(key(tsA, idA), key(tsB, idB)));
        when(repository.countConsentedAmongIds(anyList())).thenReturn(0L);
        when(teamRepository.findById(anyInt())).thenReturn(Optional.empty());
        when(repository.existsFullPrivacyInWindow(anyInt(), any(), any())).thenReturn(false);

        // The database now also holds D. Streaming asks by prepared ids only.
        Map<Integer, LogExportProjection> world = Map.of(
            idA, row(idA, "req-A", tsA),
            idB, row(idB, "req-B", tsB),
            idC, row(idC, "req-C", tsC),
            idD, row(idD, "req-D", tsD)
        );
        List<List<Integer>> requestedIdChunks = new ArrayList<>();
        when(repository.findTracesForExportByIds(anyList())).thenAnswer(invocation -> {
            List<Integer> ids = invocation.getArgument(0);
            requestedIdChunks.add(List.copyOf(ids));
            return ids.stream().map(world::get).filter(r -> r != null).toList();
        });

        TeamActivityService service = new TeamActivityService(repository, requestLogService,
            teamRepository, new ObjectMapper(), 10000, 2, 60);

        TeamActivityService.ExportPrep prep = service.prepareExport(2001, 7, null, "json", null);
        assertEquals(2, prep.count());
        assertTrue(prep.truncated());
        assertEquals(List.of(idA, idB), prep.sliceIds());
        assertEquals(tsB, prep.nextCursorTs());
        assertEquals(idB, prep.nextCursorId());

        ByteArrayOutputStream out = new ByteArrayOutputStream();
        service.writeExportFile(prep, out);

        JsonNode root = new ObjectMapper().readTree(out.toByteArray());
        assertEquals(2, root.path("count").asLong());
        List<String> requestIds = new ArrayList<>();
        root.path("traces").forEach(t -> requestIds.add(t.path("request_id").asText()));
        assertEquals(List.of("req-A", "req-B"), requestIds);
        assertFalse(requestIds.contains("req-D"));

        List<Integer> allRequested = requestedIdChunks.stream()
            .flatMap(List::stream)
            .collect(Collectors.toList());
        assertEquals(List.of(idA, idB), allRequested);
        assertFalse(allRequested.contains(idD));
    }

    private static ExportSliceCursorProjection key(Instant ts, int id) {
        return new ExportSliceCursorProjection() {
            @Override public Instant getTimestampRequest() { return ts; }
            @Override public Integer getId() { return id; }
        };
    }

    private static LogExportProjection row(int id, String requestId, Instant ts) {
        LogExportProjection row = mock(LogExportProjection.class);
        when(row.getId()).thenReturn(id);
        when(row.getRequestId()).thenReturn(requestId);
        when(row.getTimestampRequest()).thenReturn(ts);
        return row;
    }
}
