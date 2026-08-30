package de.tum.cit.aet.logos.logoswebservice.operations.repository;

/**
 * Projections behind the team activity view (issue #776).
 *
 * App administrators asked for what the statistics page gives Logos admins,
 * narrowed to their own teams and cut down to two questions: what is happening
 * right now, and what has the team spent. Everything here is therefore scoped
 * to one team by the query itself — the authorisation check upstream decides
 * *which* team, and there is no unscoped variant to reach for by mistake.
 */
public final class TeamActivityProjections {

    private TeamActivityProjections() {
    }

    /** How many of the team's requests are in each stage right now. */
    public interface LiveCountsProjection {
        /** Accepted, not yet handed to a provider. */
        long getQueued();

        /** Forwarded, no response recorded yet. */
        long getRunning();

        /** Completed within the window the caller asked about. */
        long getFinished();

        /** Of the finished ones, how many ended in an error. */
        long getFailed();
    }

    /** What one of the team's API keys has spent over the window. */
    public interface KeyUsageProjection {
        Integer getKeyId();

        String getKeyName();

        String getKeyType();

        String getEnvironment();

        long getRequestCount();

        /** Null when none of the key's requests recorded any usage. */
        Long getTotalTokens();
    }
}
