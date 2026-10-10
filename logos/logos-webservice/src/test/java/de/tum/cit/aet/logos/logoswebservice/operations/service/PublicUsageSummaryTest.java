package de.tum.cit.aet.logos.logoswebservice.operations.service;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;

import de.tum.cit.aet.logos.logoswebservice.operations.repository.AgentSessionDayProjection;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.PublicUsageRowProjection;

class PublicUsageSummaryTest {

    // A Thursday, so the current week started on 2026-10-05.
    private static final LocalDate TODAY = LocalDate.parse("2026-10-08");

    private record Row(String day, Integer teamId, String category, Integer userId, Boolean student,
                       String lane, String model, Long requests, Long tokens) implements PublicUsageRowProjection {
        @Override public String getDay() { return day; }
        @Override public Boolean getInWindow() { return true; }
        @Override public Integer getTeamId() { return teamId; }
        @Override public String getTeamName() { return "team-" + teamId; }
        @Override public String getKeyType() { return userId == null ? "application" : "developer"; }
        @Override public String getCategory() { return category; }
        @Override public Integer getUserId() { return userId; }
        @Override public Boolean getStudent() { return student; }
        @Override public String getLane() { return lane; }
        @Override public String getModel() { return model; }
        @Override public Long getRequests() { return requests; }
        @Override public Long getTokens() { return tokens; }
    }

    private record AgentDay(String day, Long sessions, Long succeeded, Long pullRequests, String starter)
            implements AgentSessionDayProjection {
        @Override public String getDay() { return day; }
        @Override public Long getSessions() { return sessions; }
        @Override public Long getSucceeded() { return succeeded; }
        @Override public Long getPullRequests() { return pullRequests; }
        @Override public String getStarter() { return starter; }
    }

    private static Row row(String day, int team, Integer user, String lane, String model, long requests, long tokens) {
        return new Row(day, team, "Research", user, user != null, lane, model, requests, tokens);
    }

    private static Map<String, Object> summarize(List<? extends PublicUsageRowProjection> window,
                                                 List<? extends PublicUsageRowProjection> all,
                                                 List<? extends AgentSessionDayProjection> windowAgent,
                                                 List<? extends AgentSessionDayProjection> allAgent) {
        Map<String, Object> stats = new LinkedHashMap<>();
        PublicUsageSummary.putAll(stats, List.copyOf(window), List.copyOf(all), List.copyOf(windowAgent),
            List.copyOf(allAgent), TODAY);
        return stats;
    }

    @Test
    @SuppressWarnings("unchecked")
    void headlineFiguresAddUpFromTheSameRows() {
        // Team 2 leads; application traffic (no user) counts in the totals but
        // not in the per-student average; a non-student person is no student.
        List<Row> rows = List.of(
            row("2026-10-01", 1, 7, "local", "m", 4, 40),
            row("2026-10-01", 2, null, "cloud", "m", 6, 60),
            new Row("2026-10-02", 2, "Research", 8, false, "unknown", "m", 1L, 1L));
        Map<String, Object> stats = new LinkedHashMap<>();
        PublicUsageSummary.putHeadline(stats, List.copyOf(rows));

        assertThat(stats.get("successful_requests")).isEqualTo(11L);
        assertThat(stats.get("students")).isEqualTo(1L);
        assertThat(stats.get("average_requests_per_user")).isEqualTo(4.0);
        assertThat((Map<String, Long>) stats.get("requests_by_key_type"))
            .containsEntry("developer", 5L).containsEntry("application", 6L).containsEntry("unknown", 0L);
        assertThat((Map<String, Long>) stats.get("local_cloud_requests"))
            .containsEntry("local", 4L).containsEntry("cloud", 6L).containsEntry("unknown", 1L);
        List<Map<String, Object>> perTeam = (List<Map<String, Object>>) stats.get("requests_per_team");
        assertThat(perTeam).extracting(t -> t.get("team_id")).containsExactly(2, 1);
        assertThat(perTeam.get(0)).containsEntry("team_name", "team-2").containsEntry("requests", 7L);
    }

    @Test
    void percentileInterpolatesLikePostgres() {
        List<Double> values = List.of(1.0, 2.0, 3.0, 4.0, 10.0);
        assertThat(PublicUsageSummary.percentile(values, 0.5)).isEqualTo(3.0);
        assertThat(PublicUsageSummary.percentile(values, 0.9)).isEqualTo(7.6);
        assertThat(PublicUsageSummary.percentile(List.of(), 0.5)).isEqualTo(0.0);
    }

    @Test
    @SuppressWarnings("unchecked")
    void perPersonFiguresArePublishedOnlyFromFiveActivePeople() {
        List<Row> four = new ArrayList<>();
        for (int user = 1; user <= 4; user++) {
            four.add(row("2026-10-01", 1, user, "local", "m", user * 10L, user * 100L));
        }
        Map<String, Object> hidden = (Map<String, Object>) summarize(four, four, List.of(), List.of()).get("usage_per_person");
        assertThat(hidden.get("suppressed")).isEqualTo(true);
        assertThat(hidden.get("requests")).isNull();

        List<Row> five = new ArrayList<>(four);
        five.add(row("2026-10-01", 1, 5, "local", "m", 50, 500));
        five.add(row("2026-10-02", 1, 5, "local", "m", 50, 500));
        Map<String, Object> shown = (Map<String, Object>) summarize(five, five, List.of(), List.of()).get("usage_per_person");
        assertThat(shown.get("suppressed")).isEqualTo(false);
        assertThat(shown.get("count")).isEqualTo(5);
        assertThat((Map<String, Double>) shown.get("requests")).containsEntry("median", 30.0);
        assertThat((Map<String, Double>) shown.get("active_days")).containsEntry("median", 1.0).containsEntry("p90", 1.6);
    }

    @Test
    @SuppressWarnings("unchecked")
    void applicationTrafficCountsForTeamsButNotForPeople() {
        List<Row> rows = List.of(
            row("2026-10-01", 1, null, "cloud", "m", 40, 400),
            row("2026-10-01", 1, 7, "local", "m", 2, 20));
        Map<String, Object> stats = summarize(rows, rows, List.of(), List.of());
        assertThat(stats.get("active_persons")).isEqualTo(1);
        assertThat(((Map<String, Object>) stats.get("usage_per_person")).get("count")).isEqualTo(1);
        Map<String, Object> perTeam = (Map<String, Object>) stats.get("usage_per_team");
        assertThat((Map<String, Double>) perTeam.get("requests")).containsEntry("median", 42.0);
        assertThat((Map<String, Long>) stats.get("local_cloud_tokens"))
            .containsEntry("local", 20L).containsEntry("cloud", 400L);
    }

    @Test
    @SuppressWarnings("unchecked")
    void modelsPastTheCapFoldIntoOneOtherRowPerLane() {
        List<Row> rows = new ArrayList<>();
        for (int i = 0; i < 10; i++) {
            rows.add(row("2026-10-01", 1, null, i % 2 == 0 ? "local" : "cloud", "model-" + i, 100 - i, 1));
        }
        Map<String, Object> models = (Map<String, Object>) summarize(rows, rows, List.of(), List.of()).get("models");
        List<Map<String, Object>> all = (List<Map<String, Object>>) models.get("all");
        assertThat(all).hasSize(PublicUsageSummary.MAX_NAMED_MODELS + 1);
        assertThat(all.get(0).get("model")).isEqualTo("model-0");
        Map<String, Object> other = all.get(all.size() - 1);
        assertThat(other.get("other")).isEqualTo(true);
        assertThat(other.get("requests")).isEqualTo(92L + 91L);
        assertThat((List<?>) models.get("local")).hasSize(5);
        assertThat((List<?>) models.get("cloud")).hasSize(5);
    }

    @Test
    @SuppressWarnings("unchecked")
    void categoriesSortByRequestsAndKeepUncategorizedAsNull() {
        List<Row> rows = List.of(
            new Row("2026-10-01", 1, null, null, false, "local", "m", 5L, 1L),
            new Row("2026-10-01", 2, "Teaching", null, false, "local", "m", 9L, 1L),
            new Row("2026-10-01", 3, "Teaching", null, false, "local", "m", 1L, 1L));
        List<Map<String, Object>> categories =
            (List<Map<String, Object>>) summarize(rows, rows, List.of(), List.of()).get("categories");
        assertThat(categories).hasSize(2);
        assertThat(categories.get(0)).containsEntry("category", "Teaching").containsEntry("teams", 2)
            .containsEntry("requests", 10L);
        assertThat(categories.get(1).get("category")).isNull();
    }

    @Test
    @SuppressWarnings("unchecked")
    void regularActivityLooksAtTheLastFourCompleteWeeks() {
        List<Row> rows = new ArrayList<>();
        // Person 1: all four complete weeks (Sep 7 .. Oct 4). Person 2: three.
        // Person 3: only the current, incomplete week. Person 4: before the range.
        for (String day : List.of("2026-09-07", "2026-09-14", "2026-09-21", "2026-10-04")) {
            rows.add(row(day, 1, 1, "local", "m", 1, 1));
        }
        for (String day : List.of("2026-09-08", "2026-09-15", "2026-09-22")) {
            rows.add(row(day, 2, 2, "local", "m", 1, 1));
        }
        rows.add(row("2026-10-06", 3, 3, "local", "m", 1, 1));
        rows.add(row("2026-09-06", 4, 4, "local", "m", 1, 1));

        Map<String, Object> regular =
            (Map<String, Object>) summarize(List.of(), rows, List.of(), List.of()).get("regular_activity");
        assertThat(regular.get("from")).isEqualTo("2026-09-07");
        assertThat(regular.get("to")).isEqualTo("2026-10-04");
        assertThat(regular.get("persons_any")).isEqualTo(2);
        assertThat(regular.get("persons_regular")).isEqualTo(2L);
        assertThat(regular.get("persons_every_week")).isEqualTo(1L);
        assertThat(regular.get("teams_regular")).isEqualTo(2L);
    }

    @Test
    @SuppressWarnings("unchecked")
    void monthlySeriesFillsGapsAndIncludesAgentSessions() {
        List<Row> rows = List.of(
            row("2026-07-15", 1, 1, "local", "m", 10, 100),
            row("2026-07-16", 2, 2, "cloud", "m", 5, 50),
            row("2026-09-01", 1, 1, "local", "m", 3, 30));
        List<AgentDay> agent = List.of(
            new AgentDay("2026-09-03", 2L, 1L, 1L, "a"),
            new AgentDay("2026-10-01", 4L, 4L, 0L, "a"),
            new AgentDay("2026-10-02", 1L, 0L, 0L, "b"));

        List<Map<String, Object>> monthly =
            (List<Map<String, Object>>) summarize(List.of(), rows, agent, agent).get("monthly");
        assertThat(monthly).extracting(m -> m.get("month"))
            .containsExactly("2026-07", "2026-08", "2026-09", "2026-10");
        assertThat(monthly.get(0)).containsEntry("requests", 15L).containsEntry("local_requests", 10L)
            .containsEntry("persons", 2).containsEntry("teams", 2);
        assertThat(monthly.get(1)).containsEntry("requests", 0L).containsEntry("persons", 0);
        assertThat(monthly.get(3)).containsEntry("agent_sessions", 5L).containsEntry("agent_users", 2);
    }

    @Test
    @SuppressWarnings("unchecked")
    void agentFiguresFollowTheWindowButKeepTheFirstSessionDay() {
        // The query cuts the window at the exact timestamp; only the all-time
        // read still carries the September session.
        List<AgentDay> all = List.of(
            new AgentDay("2026-09-03", 2L, 1L, 1L, "a"),
            new AgentDay("2026-10-01", 4L, 3L, 2L, "b"));
        List<AgentDay> window = List.of(all.get(1));
        Map<String, Object> windowed =
            (Map<String, Object>) summarize(List.of(), List.of(), window, all).get("agent");
        assertThat(windowed).containsEntry("sessions", 4L).containsEntry("users", 1)
            .containsEntry("succeeded", 3L).containsEntry("pull_requests", 2L)
            .containsEntry("first_session_day", "2026-09-03");
    }

    @Test
    @SuppressWarnings("unchecked")
    void automationSessionsCountAsSessionsButNeverAsPeople() {
        // A null starter is an automation identity: its sessions add up, the
        // people count stays with the verified human starters.
        List<AgentDay> days = List.of(
            new AgentDay("2026-10-01", 3L, 2L, 1L, null),
            new AgentDay("2026-10-01", 1L, 1L, 0L, "human"));
        Map<String, Object> stats = summarize(List.of(), List.of(), days, days);
        Map<String, Object> agent = (Map<String, Object>) stats.get("agent");
        assertThat(agent).containsEntry("sessions", 4L).containsEntry("users", 1);
        List<Map<String, Object>> monthly = (List<Map<String, Object>>) stats.get("monthly");
        assertThat(monthly.get(monthly.size() - 1))
            .containsEntry("agent_sessions", 4L).containsEntry("agent_users", 1);
    }
}
