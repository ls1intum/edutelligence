package de.tum.cit.aet.logos.logoswebservice.configuration;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * Likert (1–5) profile axes for spider charts. Keys are extensible; v1 UI
 * exposes latency / quality / price.
 */
public final class ModelProfileRatings {

    public static final List<String> AXES = List.of("latency", "quality", "price");
    public static final int MIN = 1;
    public static final int MAX = 5;

    private ModelProfileRatings() {}

    public static Map<String, Integer> normalize(Map<?, ?> raw) {
        Map<String, Integer> out = new LinkedHashMap<>();
        if (raw == null) {
            return out;
        }
        for (Map.Entry<?, ?> entry : raw.entrySet()) {
            if (entry.getKey() == null || entry.getValue() == null) {
                continue;
            }
            String key = String.valueOf(entry.getKey()).trim().toLowerCase(Locale.ROOT);
            if (key.isEmpty()) {
                continue;
            }
            Integer score = toLikert(entry.getValue());
            if (score != null) {
                out.put(key, score);
            }
        }
        return out;
    }

    public static Integer toLikert(Object value) {
        int n;
        if (value instanceof Number num) {
            n = num.intValue();
        }
        else {
            try {
                n = Integer.parseInt(String.valueOf(value).trim());
            }
            catch (NumberFormatException e) {
                return null;
            }
        }
        if (n < MIN || n > MAX) {
            return null;
        }
        return n;
    }
}
