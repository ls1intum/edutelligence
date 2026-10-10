package de.tum.cit.aet.logos.logoswebservice.operations.service;

import java.time.DayOfWeek;
import java.time.LocalDate;
import java.time.YearMonth;
import java.time.temporal.TemporalAdjusters;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.TreeMap;
import java.util.function.Function;

import de.tum.cit.aet.logos.logoswebservice.operations.repository.AgentSessionDayProjection;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.PublicUsageRowProjection;

/**
 * Turns the public usage rows (one per day, team, user, lane and model) into
 * the distributions, shares and monthly series of the public stats page.
 *
 * <p>Pure computation, no database access: the caller passes the rows of the
 * selected window, the rows of all time (for the monthly series and the
 * regular-activity counts, which do not follow the window) and the Logos Agent
 * session days.
 */
final class PublicUsageSummary {

    /**
     * Fewest active people for which per-person medians and percentiles are
     * published. Below that, a percentile is close to one person's numbers.
     */
    static final int MIN_PERSON_COHORT = 5;

    /** Models listed by name per lane; the rest fold into one "other" row. */
    static final int MAX_NAMED_MODELS = 8;

    /** Weeks looked back for the regular-activity counts. */
    static final int REGULAR_WEEKS = 4;

    /** Active weeks (of {@link #REGULAR_WEEKS}) that make someone a regular user. */
    static final int REGULAR_MIN_WEEKS = 3;

    private PublicUsageSummary() {
    }

    /** Fills {@code stats} with every figure derived from the usage rows. */
    static void putAll(Map<String, Object> stats,
                       List<PublicUsageRowProjection> windowRows,
                       List<PublicUsageRowProjection> allRows,
                       List<AgentSessionDayProjection> windowAgentDays,
                       List<AgentSessionDayProjection> allAgentDays,
                       LocalDate today) {
        long tokens = 0;
        Map<String, Long> laneTokens = new LinkedHashMap<>();
        laneTokens.put("local", 0L);
        laneTokens.put("cloud", 0L);
        laneTokens.put("unknown", 0L);
        Set<Integer> persons = new HashSet<>();
        Set<Integer> teams = new HashSet<>();
        for (PublicUsageRowProjection row : windowRows) {
            tokens += tokens(row);
            laneTokens.merge(lane(row), tokens(row), Long::sum);
            if (row.getUserId() != null) {
                persons.add(row.getUserId());
            }
            teams.add(row.getTeamId());
        }

        stats.put("tokens", tokens);
        stats.put("local_cloud_tokens", laneTokens);
        stats.put("active_persons", persons.size());
        stats.put("active_teams", teams.size());
        stats.put("usage_per_person", usageDistribution(
            windowRows.stream().filter(r -> r.getUserId() != null).toList(),
            PublicUsageRowProjection::getUserId, MIN_PERSON_COHORT));
        stats.put("usage_per_team", usageDistribution(windowRows, PublicUsageRowProjection::getTeamId, 1));
        stats.put("categories", categories(windowRows));
        stats.put("models", models(windowRows));
        stats.put("regular_activity", regularActivity(allRows, today));
        stats.put("monthly", monthly(allRows, allAgentDays, today));
        stats.put("agent", agent(windowAgentDays, allAgentDays));
    }

    private static long requests(PublicUsageRowProjection row) {
        return row.getRequests() == null ? 0 : row.getRequests();
    }

    private static long tokens(PublicUsageRowProjection row) {
        return row.getTokens() == null ? 0 : row.getTokens();
    }

    private static String lane(PublicUsageRowProjection row) {
        return row.getLane() == null ? "unknown" : row.getLane();
    }

    /**
     * Requests, tokens and active days per unit (person or team) over the
     * rows, as median and 90th percentile. Values are null when fewer than
     * {@code minCohort} units are active.
     */
    private static Map<String, Object> usageDistribution(List<PublicUsageRowProjection> rows,
                                                         Function<PublicUsageRowProjection, Integer> unitOf,
                                                         int minCohort) {
        Map<Integer, long[]> perUnit = new HashMap<>();
        Map<Integer, Set<String>> daysPerUnit = new HashMap<>();
        for (PublicUsageRowProjection row : rows) {
            Integer unit = unitOf.apply(row);
            long[] sums = perUnit.computeIfAbsent(unit, k -> new long[2]);
            sums[0] += requests(row);
            sums[1] += tokens(row);
            daysPerUnit.computeIfAbsent(unit, k -> new HashSet<>()).add(row.getDay());
        }

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("count", perUnit.size());
        boolean published = perUnit.size() >= minCohort && !perUnit.isEmpty();
        result.put("suppressed", !published);
        List<Double> requests = perUnit.values().stream().map(s -> (double) s[0]).toList();
        List<Double> tokens = perUnit.values().stream().map(s -> (double) s[1]).toList();
        List<Double> days = daysPerUnit.values().stream().map(d -> (double) d.size()).toList();
        result.put("requests", published ? percentiles(requests) : null);
        result.put("tokens", published ? percentiles(tokens) : null);
        result.put("active_days", published ? percentiles(days) : null);
        return result;
    }

    private static Map<String, Double> percentiles(List<Double> values) {
        List<Double> sorted = values.stream().sorted().toList();
        Map<String, Double> result = new LinkedHashMap<>();
        result.put("median", percentile(sorted, 0.5));
        result.put("p90", percentile(sorted, 0.9));
        return result;
    }

    /** Linear interpolation between closest ranks, like Postgres percentile_cont. */
    static double percentile(List<Double> sorted, double fraction) {
        if (sorted.isEmpty()) {
            return 0.0;
        }
        double position = fraction * (sorted.size() - 1);
        int lower = (int) Math.floor(position);
        int upper = (int) Math.ceil(position);
        double value = sorted.get(lower) + (sorted.get(upper) - sorted.get(lower)) * (position - lower);
        return Math.round(value * 100.0) / 100.0;
    }

    private static List<Map<String, Object>> categories(List<PublicUsageRowProjection> rows) {
        Map<String, long[]> sums = new HashMap<>();
        Map<String, Set<Integer>> teams = new HashMap<>();
        for (PublicUsageRowProjection row : rows) {
            String category = row.getCategory();
            long[] s = sums.computeIfAbsent(category, k -> new long[2]);
            s[0] += requests(row);
            s[1] += tokens(row);
            teams.computeIfAbsent(category, k -> new HashSet<>()).add(row.getTeamId());
        }
        List<Map<String, Object>> result = new ArrayList<>();
        sums.entrySet().stream()
            .sorted(Comparator.<Map.Entry<String, long[]>>comparingLong(e -> -e.getValue()[0])
                .thenComparing(e -> e.getKey() == null ? "" : e.getKey()))
            .forEach(e -> {
                Map<String, Object> entry = new LinkedHashMap<>();
                entry.put("category", e.getKey());
                entry.put("teams", teams.get(e.getKey()).size());
                entry.put("requests", e.getValue()[0]);
                entry.put("tokens", e.getValue()[1]);
                result.add(entry);
            });
        return result;
    }

    private static Map<String, Object> models(List<PublicUsageRowProjection> rows) {
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("all", modelRanking(rows));
        result.put("local", modelRanking(rows.stream().filter(r -> "local".equals(lane(r))).toList()));
        result.put("cloud", modelRanking(rows.stream().filter(r -> "cloud".equals(lane(r))).toList()));
        return result;
    }

    /**
     * Models by successful requests, most first. Past {@link #MAX_NAMED_MODELS}
     * the rest are summed into one row with {@code other = true}.
     */
    private static List<Map<String, Object>> modelRanking(List<PublicUsageRowProjection> rows) {
        Map<String, long[]> sums = new HashMap<>();
        for (PublicUsageRowProjection row : rows) {
            String model = row.getModel() == null || row.getModel().isBlank() ? "Unknown model" : row.getModel();
            long[] s = sums.computeIfAbsent(model, k -> new long[2]);
            s[0] += requests(row);
            s[1] += tokens(row);
        }
        List<Map.Entry<String, long[]>> sorted = sums.entrySet().stream()
            .sorted(Comparator.<Map.Entry<String, long[]>>comparingLong(e -> -e.getValue()[0])
                .thenComparing(Map.Entry::getKey))
            .toList();

        List<Map<String, Object>> result = new ArrayList<>();
        long otherRequests = 0;
        long otherTokens = 0;
        for (int i = 0; i < sorted.size(); i++) {
            Map.Entry<String, long[]> e = sorted.get(i);
            if (i < MAX_NAMED_MODELS) {
                result.add(modelEntry(e.getKey(), e.getValue()[0], e.getValue()[1], false));
            } else {
                otherRequests += e.getValue()[0];
                otherTokens += e.getValue()[1];
            }
        }
        if (sorted.size() > MAX_NAMED_MODELS) {
            result.add(modelEntry(null, otherRequests, otherTokens, true));
        }
        return result;
    }

    private static Map<String, Object> modelEntry(String model, long requests, long tokens, boolean other) {
        Map<String, Object> entry = new LinkedHashMap<>();
        entry.put("model", model);
        entry.put("requests", requests);
        entry.put("tokens", tokens);
        entry.put("other", other);
        return entry;
    }

    /**
     * People and teams active in at least {@link #REGULAR_MIN_WEEKS} and in all
     * of the last {@link #REGULAR_WEEKS} complete weeks (Monday to Sunday,
     * UTC). Independent of the selected window.
     */
    private static Map<String, Object> regularActivity(List<PublicUsageRowProjection> rows, LocalDate today) {
        LocalDate currentWeek = today.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY));
        LocalDate from = currentWeek.minusWeeks(REGULAR_WEEKS);
        Map<Integer, Set<LocalDate>> personWeeks = new HashMap<>();
        Map<Integer, Set<LocalDate>> teamWeeks = new HashMap<>();
        for (PublicUsageRowProjection row : rows) {
            LocalDate day = LocalDate.parse(row.getDay());
            if (day.isBefore(from) || !day.isBefore(currentWeek)) {
                continue;
            }
            LocalDate week = day.with(TemporalAdjusters.previousOrSame(DayOfWeek.MONDAY));
            if (row.getUserId() != null) {
                personWeeks.computeIfAbsent(row.getUserId(), k -> new HashSet<>()).add(week);
            }
            teamWeeks.computeIfAbsent(row.getTeamId(), k -> new HashSet<>()).add(week);
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("weeks", REGULAR_WEEKS);
        result.put("min_weeks", REGULAR_MIN_WEEKS);
        result.put("from", from.toString());
        result.put("to", currentWeek.minusDays(1).toString());
        result.put("persons_any", personWeeks.size());
        result.put("persons_regular", countAtLeast(personWeeks, REGULAR_MIN_WEEKS));
        result.put("persons_every_week", countAtLeast(personWeeks, REGULAR_WEEKS));
        result.put("teams_any", teamWeeks.size());
        result.put("teams_regular", countAtLeast(teamWeeks, REGULAR_MIN_WEEKS));
        result.put("teams_every_week", countAtLeast(teamWeeks, REGULAR_WEEKS));
        return result;
    }

    private static long countAtLeast(Map<Integer, Set<LocalDate>> weeks, int min) {
        return weeks.values().stream().filter(w -> w.size() >= min).count();
    }

    /**
     * One entry per calendar month (UTC) from the first month with usage or a
     * Logos Agent session through the current one, gaps filled with zeroes.
     */
    private static List<Map<String, Object>> monthly(List<PublicUsageRowProjection> rows,
                                                     List<AgentSessionDayProjection> agentDays,
                                                     LocalDate today) {
        TreeMap<YearMonth, MonthAccumulator> months = new TreeMap<>();
        for (PublicUsageRowProjection row : rows) {
            MonthAccumulator m = months.computeIfAbsent(YearMonth.from(LocalDate.parse(row.getDay())),
                k -> new MonthAccumulator());
            m.requests += requests(row);
            m.tokens += tokens(row);
            if ("local".equals(lane(row))) {
                m.localRequests += requests(row);
            }
            m.teams.add(row.getTeamId());
            if (row.getUserId() != null) {
                m.persons.add(row.getUserId());
                if (Boolean.TRUE.equals(row.getStudent())) {
                    m.students.add(row.getUserId());
                }
            }
        }
        for (AgentSessionDayProjection day : agentDays) {
            MonthAccumulator m = months.computeIfAbsent(YearMonth.from(LocalDate.parse(day.getDay())),
                k -> new MonthAccumulator());
            m.agentSessions += day.getSessions() == null ? 0 : day.getSessions();
            if (day.getStarter() != null) {
                m.agentStarters.add(day.getStarter());
            }
        }

        List<Map<String, Object>> result = new ArrayList<>();
        if (months.isEmpty()) {
            return result;
        }
        YearMonth last = YearMonth.from(today);
        for (YearMonth month = months.firstKey(); !month.isAfter(last); month = month.plusMonths(1)) {
            MonthAccumulator m = months.getOrDefault(month, new MonthAccumulator());
            Map<String, Object> entry = new LinkedHashMap<>();
            entry.put("month", month.toString());
            entry.put("teams", m.teams.size());
            entry.put("persons", m.persons.size());
            entry.put("students", m.students.size());
            entry.put("requests", m.requests);
            entry.put("local_requests", m.localRequests);
            entry.put("tokens", m.tokens);
            entry.put("agent_sessions", m.agentSessions);
            entry.put("agent_users", m.agentStarters.size());
            result.add(entry);
        }
        return result;
    }

    private static final class MonthAccumulator {
        long requests;
        long localRequests;
        long tokens;
        long agentSessions;
        final Set<Integer> teams = new HashSet<>();
        final Set<Integer> persons = new HashSet<>();
        final Set<Integer> students = new HashSet<>();
        final Set<String> agentStarters = new HashSet<>();
    }

    /**
     * Logos Agent figures for the window and the day of the first published
     * session ever. The window days are already cut at the exact window start
     * by the query; {@code users} counts verified human starters only (a null
     * starter is an automation identity and still adds to the sessions).
     */
    private static Map<String, Object> agent(List<AgentSessionDayProjection> windowDays,
                                             List<AgentSessionDayProjection> allDays) {
        long sessions = 0;
        long succeeded = 0;
        long pullRequests = 0;
        Set<String> starters = new HashSet<>();
        for (AgentSessionDayProjection day : windowDays) {
            sessions += Objects.requireNonNullElse(day.getSessions(), 0L);
            succeeded += Objects.requireNonNullElse(day.getSucceeded(), 0L);
            pullRequests += Objects.requireNonNullElse(day.getPullRequests(), 0L);
            if (day.getStarter() != null) {
                starters.add(day.getStarter());
            }
        }
        String first = null;
        for (AgentSessionDayProjection day : allDays) {
            if (first == null || day.getDay().compareTo(first) < 0) {
                first = day.getDay();
            }
        }
        Map<String, Object> result = new LinkedHashMap<>();
        result.put("sessions", sessions);
        result.put("users", starters.size());
        result.put("succeeded", succeeded);
        result.put("pull_requests", pullRequests);
        result.put("first_session_day", first);
        return result;
    }
}
