package de.tum.cit.aet.logos.logoswebservice.common;

import java.io.IOException;
import java.sql.SQLException;

import javax.sql.DataSource;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;
import org.springframework.web.servlet.HandlerMapping;

import com.zaxxer.hikari.HikariDataSource;
import com.zaxxer.hikari.HikariPoolMXBean;

import de.tum.cit.aet.logos.logoswebservice.auth.AuthContext;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

/**
 * Logs one line per request with its total time split into JWT decode, user
 * auth/sync and handler, plus the DB pool state at start and end — enough to
 * tell a slow Keycloak, a slow or lock-bound user sync, and pool exhaustion
 * apart without reproducing the load.
 *
 * <p>Runs ahead of every other filter, Spring Security included, so the total
 * covers the whole application. Time spent queued for a Tomcat worker thread
 * happens before any filter and is not included. For an async response
 * (streamed inference) the total ends when the request thread is released,
 * not when the stream finishes.
 *
 * <p>Requests at or above {@code logos.request-timing.slow-threshold-ms} are
 * logged at WARN, the rest at INFO.
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class RequestTimingFilter extends OncePerRequestFilter {

    private static final Logger log = LoggerFactory.getLogger(RequestTimingFilter.class);

    private final boolean enabled;
    private final long slowThresholdMs;
    private final HikariDataSource hikari;

    public RequestTimingFilter(
            @Value("${logos.request-timing.enabled:true}") boolean enabled,
            @Value("${logos.request-timing.slow-threshold-ms:1000}") long slowThresholdMs,
            ObjectProvider<DataSource> dataSource) {
        this.enabled = enabled;
        this.slowThresholdMs = slowThresholdMs;
        this.hikari = unwrapHikari(dataSource.getIfAvailable());
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        return !enabled;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        long start = System.nanoTime();
        String poolAtStart = poolState();
        RequestTiming timing = RequestTiming.open();
        Throwable failure = null;
        try {
            chain.doFilter(request, response);
        } catch (IOException | ServletException | RuntimeException e) {
            failure = e;
            throw e;
        } finally {
            RequestTiming.close();
            long end = System.nanoTime();
            try {
                logRequest(request, response, timing, start, end, poolAtStart, failure);
            } catch (RuntimeException e) {
                log.debug("Could not log request timing", e);
            }
        }
    }

    private void logRequest(HttpServletRequest request, HttpServletResponse response, RequestTiming timing,
                            long start, long end, String poolAtStart, Throwable failure) {
        long totalMs = toMs(end - start);
        Object route = request.getAttribute(HandlerMapping.BEST_MATCHING_PATTERN_ATTRIBUTE);
        Object auth = request.getAttribute("authContext");
        Integer userId = auth instanceof AuthContext ctx ? ctx.userId() : null;
        // An exception escaping the chain still shows the status set before it was
        // thrown; the container answers it with a 500, and its error dispatch is
        // not filtered again, so record that here.
        int status = failure != null && response.getStatus() < 400 ? 500 : response.getStatus();

        StringBuilder line = new StringBuilder(256)
            .append("request ").append(request.getMethod()).append(' ').append(request.getRequestURI())
            .append(" route=").append(route != null ? route : "-")
            .append(" status=").append(status)
            .append(" totalMs=").append(totalMs)
            .append(" jwtMs=").append(msOrDash(timing.jwtDecodeNanos))
            .append(" authMs=").append(msOrDash(timing.authNanos))
            .append(" sync=").append(timing.synced ? "yes" : "no");
        if (timing.synced && timing.syncTeams >= 0) {
            line.append(" syncUserMs=").append(toMs(timing.syncUserNanos))
                .append(" syncResolveMs=").append(toMs(timing.syncResolveNanos))
                .append(" syncLockMs=").append(toMs(timing.syncLockNanos))
                .append(" syncWriteMs=").append(toMs(timing.syncWriteNanos))
                .append(" syncTeams=").append(timing.syncTeams);
        }
        line.append(" handlerMs=")
            .append(timing.handlerStartNanos >= 0 ? String.valueOf(toMs(end - timing.handlerStartNanos)) : "-")
            .append(" async=").append(request.isAsyncStarted())
            .append(" user=").append(userId != null ? userId : "-")
            .append(" poolStart=").append(poolAtStart)
            .append(" poolEnd=").append(poolState());
        if (failure != null) {
            line.append(" exception=").append(failure.getClass().getSimpleName());
        }

        if (totalMs >= slowThresholdMs) {
            log.warn("{}", line);
        } else {
            log.info("{}", line);
        }
    }

    /** {@code active/idle/waiting} connections, or {@code -} before the pool has started. */
    private String poolState() {
        if (hikari == null) return "-";
        HikariPoolMXBean pool = hikari.getHikariPoolMXBean();
        if (pool == null) return "-";
        return pool.getActiveConnections() + "/" + pool.getIdleConnections() + "/" + pool.getThreadsAwaitingConnection();
    }

    private static HikariDataSource unwrapHikari(DataSource dataSource) {
        if (dataSource == null) return null;
        try {
            return dataSource.isWrapperFor(HikariDataSource.class) ? dataSource.unwrap(HikariDataSource.class) : null;
        } catch (SQLException e) {
            return null;
        }
    }

    private static String msOrDash(long nanos) {
        return nanos >= 0 ? String.valueOf(toMs(nanos)) : "-";
    }

    private static long toMs(long nanos) {
        return nanos / 1_000_000;
    }
}
