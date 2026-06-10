package de.tum.cit.aet.logos.logoswebservice.operations.service;

import java.sql.Timestamp;
import java.time.Instant;
import java.time.ZoneOffset;
import java.time.ZonedDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.springframework.stereotype.Service;

import de.tum.cit.aet.logos.logoswebservice.configuration.entity.TokenPrice;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.TokenPriceRepository;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.TokenTypeRepository;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.BudgetBucketProjection;
import de.tum.cit.aet.logos.logoswebservice.operations.repository.LogEntryBillingRepository;

@Service
public class BillingService {

    private static final Map<Integer, String> BUCKET_TO_PG_INTERVAL = Map.of(
            3600, "hour",
            86400, "day",
            604800, "week",
            2592000, "month"
    );

    private final TokenTypeRepository tokenTypeRepository;
    private final TokenPriceRepository tokenPriceRepository;
    private final LogEntryBillingRepository logEntryBillingRepository;

    public BillingService(TokenTypeRepository tokenTypeRepository,
                          TokenPriceRepository tokenPriceRepository,
                          LogEntryBillingRepository logEntryBillingRepository) {
        this.tokenTypeRepository = tokenTypeRepository;
        this.tokenPriceRepository = tokenPriceRepository;
        this.logEntryBillingRepository = logEntryBillingRepository;
    }

    public Map<String, Object> addBilling(String typeName, double typeCost,
                                          String validFrom, Integer modelId) {
        Integer typeId = tokenTypeRepository.findByName(typeName)
            .orElseThrow(() -> new IllegalArgumentException("Token name not found"))
            .getId();

        Instant validFromInstant = ZonedDateTime.parse(validFrom.replace("Z", "+00:00"))
                                                .withZoneSameInstant(ZoneOffset.UTC).toInstant();

        TokenPrice price = new TokenPrice();
        price.setTypeId(typeId);
        price.setValidFrom(validFromInstant);
        price.setPricePerKToken(Math.round(typeCost));
        if (modelId != null) price.setModelId(modelId);
        TokenPrice saved = tokenPriceRepository.save(price);
        return Map.of("result", "Successfully added billing", "billing-id", saved.getId());
    }

    public Map<String, Object> getTeamBudgetHistory(String startIso, String endIso) {
        Timestamp startTs = isoToTimestamp(startIso);
        Timestamp endTs = isoToTimestamp(endIso);
        long spanSeconds = spanSeconds(startIso, endIso);
        int bucketSeconds = BillingService.chooseBillingBucketSeconds(spanSeconds);
        String interval = BUCKET_TO_PG_INTERVAL.getOrDefault(bucketSeconds, "day");

        List<Map<String, Object>> buckets = logEntryBillingRepository
            .findTeamBudgetHistory(startTs, endTs, interval).stream()
            .map(p -> {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("team_id", p.getTeamId());
                m.put("team_name", p.getTeamName());
                m.put("bucket_ts", ts(p.getBucketTs()));
                m.put("cost_micro_cents", p.getCostMicroCents());
                return m;
            })
            .toList();

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("buckets", buckets);
        result.put("bucket_seconds", bucketSeconds);
        result.put("start_iso", startIso);
        result.put("end_iso", endIso);
        return result;
    }

    public Map<String, Object> getKeyBudgetHistory(int teamId, String startIso, String endIso) {
        Timestamp startTs = isoToTimestamp(startIso);
        Timestamp endTs = isoToTimestamp(endIso);
        long spanSeconds = spanSeconds(startIso, endIso);
        int bucketSeconds = BillingService.chooseBillingBucketSeconds(spanSeconds);
        String interval = BUCKET_TO_PG_INTERVAL.getOrDefault(bucketSeconds, "day");

        List<Map<String, Object>> buckets = logEntryBillingRepository
            .findKeyBudgetHistory(teamId, startTs, endTs, interval).stream()
            .map(p -> {
                Map<String, Object> m = new LinkedHashMap<>();
                m.put("api_key_id", p.getApiKeyId());
                m.put("api_key_name", p.getApiKeyName());
                m.put("bucket_ts", ts(p.getBucketTs()));
                m.put("cost_micro_cents", p.getCostMicroCents());
                return m;
            })
            .toList();

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("buckets", buckets);
        result.put("bucket_seconds", bucketSeconds);
        result.put("start_iso", startIso);
        result.put("end_iso", endIso);
        return result;
    }

    static int chooseBillingBucketSeconds(long spanSeconds) {
        long day = 86400;
        if (spanSeconds <= day) return 3600;
        if (spanSeconds <= 32 * day) return 86400;
        if (spanSeconds <= 186 * day) return 604800;
        return 2592000;
    }

    private static long spanSeconds(String startIso, String endIso) {
        ZonedDateTime start = ZonedDateTime.parse(startIso.replace("Z", "+00:00"))
                                           .withZoneSameInstant(ZoneOffset.UTC);
        ZonedDateTime end   = ZonedDateTime.parse(endIso.replace("Z", "+00:00"))
                                           .withZoneSameInstant(ZoneOffset.UTC);
        return Math.max(end.toEpochSecond() - start.toEpochSecond(), 0);
    }

    private static Timestamp isoToTimestamp(String iso) {
        return Timestamp.from(ZonedDateTime.parse(iso.replace("Z", "+00:00"))
                                        .withZoneSameInstant(ZoneOffset.UTC).toInstant());
    }

    private static String ts(java.time.Instant t) {
        return t != null ? t.toString() : null;
    }
}
