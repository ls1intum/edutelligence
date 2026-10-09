package de.tum.cit.aet.logos.logoswebservice.operations.service;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.lang.reflect.Method;

import org.junit.jupiter.api.Test;
import org.springframework.transaction.annotation.Isolation;
import org.springframework.transaction.annotation.Transactional;

/**
 * publicStats reads several aggregates that must agree. The enclosing
 * repeatable-read transaction is what keeps a concurrent success from making
 * the headline and breakdown totals disagree; this check guards the
 * annotation so a later edit cannot drop it quietly.
 */
class StatsServicePublicStatsTransactionTest {

    @Test
    void publicStatsRunsInOneRepeatableReadTransaction() throws Exception {
        Method method = StatsService.class.getMethod("publicStats", String.class);
        Transactional transactional = method.getAnnotation(Transactional.class);
        assertNotNull(transactional, "publicStats must be @Transactional so the Spring proxy opens one snapshot");
        assertTrue(transactional.readOnly());
        assertEquals(Isolation.REPEATABLE_READ, transactional.isolation());
    }
}
