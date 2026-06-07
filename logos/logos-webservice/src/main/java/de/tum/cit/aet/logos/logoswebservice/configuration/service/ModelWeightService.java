package de.tum.cit.aet.logos.logoswebservice.configuration.service;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import de.tum.cit.aet.logos.logoswebservice.configuration.entity.Model;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelRepository;

@Service
public class ModelWeightService {

    private static final int BASE_FEEDBACK = 2;
    private static final int FEEDBACK_SCALE = 2;

    private final ModelRepository modelRepository;
    private final JdbcTemplate jdbcTemplate;

    public ModelWeightService(ModelRepository modelRepository, JdbcTemplate jdbcTemplate) {
        this.modelRepository = modelRepository;
        this.jdbcTemplate = jdbcTemplate;
    }

    @Transactional
    public void rebalanceAfterAdd(int newModelId, Integer worseLatencyId, Integer worseAccuracyId,
                                   Integer worseCostId, Integer worseQualityId) {
        List<Model> all = modelRepository.findAll();
        List<int[]> lat = sortedList(all, "latency", newModelId);
        List<int[]> acc = sortedList(all, "accuracy", newModelId);
        List<int[]> cos = sortedList(all, "cost", newModelId);
        List<int[]> qua = sortedList(all, "quality", newModelId);
        addModel(lat, worseLatencyId, newModelId);
        addModel(acc, worseAccuracyId, newModelId);
        addModel(cos, worseCostId, newModelId);
        addModel(qua, worseQualityId, newModelId);
        writeWeights(lat, acc, cos, qua);
    }

    @Transactional
    public void rebalanceAfterFeedback(int modelId, String category, int feedback) {
        if (!java.util.Set.of("latency", "accuracy", "cost", "quality").contains(category)) {
            throw new IllegalArgumentException("Invalid category: " + category);
        }
        List<Model> all = modelRepository.findAll();
        List<int[]> sorted = sortedList(all, category, -1);

        int idx = indexOf(sorted, modelId);
        if (idx == -1) throw new IllegalArgumentException("Model not found: " + modelId);

        sorted.get(idx)[0] += feedback;

        int unique = countUnique(sorted);
        int[][] reset = scoreWithRebalance(sorted, unique);
        int[] diffs = new int[sorted.size()];
        for (int i = 0; i < sorted.size(); i++) {
            diffs[i] = reset[i][0] - sorted.get(i)[0];
        }

        while (idx > 0 && sorted.get(idx)[0] < sorted.get(idx - 1)[0]) {
            int[] tmp = sorted.get(idx);
            sorted.set(idx, sorted.get(idx - 1));
            sorted.set(idx - 1, tmp);
            sorted.get(idx)[0] = reset[idx][0] - diffs[idx - 1];
            idx--;
        }
        while (idx < sorted.size() - 1 && sorted.get(idx)[0] > sorted.get(idx + 1)[0]) {
            int[] tmp = sorted.get(idx);
            sorted.set(idx, sorted.get(idx + 1));
            sorted.set(idx + 1, tmp);
            sorted.get(idx)[0] = reset[idx][0] - diffs[idx + 1];
            idx++;
        }

        int[][] arr = sorted.stream().map(e -> new int[]{e[0], e[1]}).toArray(int[][]::new);
        int[][] balanced = rebalance(arr);
        for (int i = 0; i < sorted.size(); i++) {
            sorted.set(i, balanced[i]);
        }

        String col = switch (category) {
            case "latency" -> "weight_latency";
            case "accuracy" -> "weight_accuracy";
            case "cost" -> "weight_cost";
            case "quality" -> "weight_quality";
            default -> throw new IllegalArgumentException("Invalid category: " + category);
        };
        for (int[] entry : sorted) {
            jdbcTemplate.update("UPDATE models SET " + col + "=? WHERE id=?", entry[0], entry[1]);
        }
    }

    @Transactional
    public void rebalanceAfterDelete(int deletedModelId) {
        List<Model> all = modelRepository.findAll();
        List<int[]> lat = sortedList(all, "latency", -1);
        List<int[]> acc = sortedList(all, "accuracy", -1);
        List<int[]> cos = sortedList(all, "cost", -1);
        List<int[]> qua = sortedList(all, "quality", -1);
        removeModel(lat, deletedModelId);
        removeModel(acc, deletedModelId);
        removeModel(cos, deletedModelId);
        removeModel(qua, deletedModelId);
        writeWeights(lat, acc, cos, qua);
        modelRepository.deleteById(deletedModelId);
    }

    void testAddModel(List<int[]> list, Integer worseId, int newId) {
        addModel(list, worseId, newId);
    }

    void testRemoveModel(List<int[]> list, int modelId) {
        removeModel(list, modelId);
    }

    private List<int[]> sortedList(List<Model> models, String dim, int excludeId) {
        return models.stream()
            .filter(m -> !m.getId().equals(excludeId))
            .map(m -> new int[]{ weight(m, dim), m.getId() })
            .sorted(Comparator.comparingInt(a -> a[0]))
            .collect(Collectors.toCollection(ArrayList::new));
    }

    private int weight(Model m, String dim) {
        return switch (dim) {
            case "latency" -> m.getWeightLatency() != null ? m.getWeightLatency() : 0;
            case "accuracy" -> m.getWeightAccuracy() != null ? m.getWeightAccuracy() : 0;
            case "cost" -> m.getWeightCost() != null ? m.getWeightCost() : 0;
            case "quality" -> m.getWeightQuality() != null ? m.getWeightQuality() : 0;
            default -> 0;
        };
    }

    private void addModel(List<int[]> models, Integer worseId, int newId) {
        int index;
        if (worseId == null) {
            index = 0;
        } else {
            index = indexOf(models, worseId);
            index = (index == -1) ? 0 : index + 1;
        }

        int uniqueBefore = countUnique(models);
        int[] newModel = new int[]{ score(0, uniqueBefore), newId };

        int[][] resetScores = scoreWithRebalance(models, uniqueBefore);
        int[] diffs = new int[models.size()];
        for (int i = 0; i < models.size(); i++) {
            diffs[i] = resetScores[i][0] - models.get(i)[0];
        }

        int feedbackShift = models.size() >= 2
            ? (models.get(0)[0] + models.get(models.size() - 1)[0]) / 2
            : 0;

        if (index >= models.size()) {
            models.add(newModel);
            diffs = appendInt(diffs, -feedbackShift);
        } else {
            models.add(index, newModel);
            diffs = insertInt(diffs, index, -feedbackShift);
        }

        int uniqueAfter = countUnique(models);
        int[][] values = scoreWithRebalance(models, uniqueAfter);
        for (int i = 0; i < values.length; i++) {
            values[i][0] -= diffs[i];
        }
        int[][] finalValues = rebalance(values);
        for (int i = 0; i < models.size(); i++) {
            models.set(i, new int[]{ finalValues[i][0], finalValues[i][1] });
        }
    }

    private void removeModel(List<int[]> models, int modelId) {
        int uniqueBefore = countUnique(models);
        int[][] resetScores = scoreWithRebalance(models, uniqueBefore);
        int[] diffs = new int[models.size()];
        for (int i = 0; i < models.size(); i++) {
            diffs[i] = resetScores[i][0] - models.get(i)[0];
        }

        int index = indexOf(models, modelId);
        if (index == -1) return;
        models.remove(index);
        diffs = removeInt(diffs, index);

        if (models.isEmpty()) return;

        int uniqueAfter = countUnique(models);
        int[][] values = scoreWithRebalance(models, uniqueAfter);
        for (int i = 0; i < values.length; i++) {
            values[i][0] -= diffs[i];
        }
        int[][] finalValues = rebalance(values);
        for (int i = 0; i < models.size(); i++) {
            models.set(i, new int[]{ finalValues[i][0], finalValues[i][1] });
        }
    }

    private int[][] scoreWithRebalance(List<int[]> models, int unique) {
        int[][] scored = new int[models.size()][2];
        for (int i = 0; i < models.size(); i++) {
            scored[i][0] = score(i, unique);
            scored[i][1] = models.get(i)[1];
        }
        return rebalance(scored);
    }

    private int score(int position, int unique) {
        if (unique == 0) return 0;
        return FEEDBACK_SCALE * (-BASE_FEEDBACK * unique + 2 * BASE_FEEDBACK * position);
    }

    private int[][] rebalance(int[][] models) {
        if (models.length == 0) return models;
        int n = models.length;
        int center = ((n & 1) == 1)
            ? models[n / 2][0]
            : (models[n / 2 - 1][0] + models[n / 2][0]) / 2;
        int[][] result = new int[n][2];
        for (int i = 0; i < n; i++) {
            result[i][0] = models[i][0] - center;
            result[i][1] = models[i][1];
        }
        return result;
    }

    private int indexOf(List<int[]> models, int modelId) {
        for (int i = 0; i < models.size(); i++) {
            if (models.get(i)[1] == modelId) return i;
        }
        return -1;
    }

    private int countUnique(List<int[]> models) {
        return (int) models.stream().mapToInt(m -> m[0]).distinct().count();
    }

    private void writeWeights(List<int[]> lat, List<int[]> acc, List<int[]> cos, List<int[]> qua) {
        Map<Integer, int[]> weights = new HashMap<>();
        for (int[] e : lat) weights.computeIfAbsent(e[1], k -> new int[4])[0] = e[0];
        for (int[] e : acc) weights.computeIfAbsent(e[1], k -> new int[4])[1] = e[0];
        for (int[] e : cos) weights.computeIfAbsent(e[1], k -> new int[4])[2] = e[0];
        for (int[] e : qua) weights.computeIfAbsent(e[1], k -> new int[4])[3] = e[0];
        for (Map.Entry<Integer, int[]> entry : weights.entrySet()) {
            int id = entry.getKey();
            int[] w = entry.getValue();
            jdbcTemplate.update(
                "UPDATE models SET weight_latency=?, weight_accuracy=?, weight_cost=?, weight_quality=? WHERE id=?",
                w[0], w[1], w[2], w[3], id
            );
        }
    }

    private int[] appendInt(int[] arr, int val) {
        int[] result = Arrays.copyOf(arr, arr.length + 1);
        result[arr.length] = val;
        return result;
    }

    private int[] insertInt(int[] arr, int pos, int val) {
        int[] result = new int[arr.length + 1];
        System.arraycopy(arr, 0, result, 0, pos);
        result[pos] = val;
        System.arraycopy(arr, pos, result, pos + 1, arr.length - pos);
        return result;
    }

    private int[] removeInt(int[] arr, int pos) {
        int[] result = new int[arr.length - 1];
        System.arraycopy(arr, 0, result, 0, pos);
        System.arraycopy(arr, pos + 1, result, pos, arr.length - pos - 1);
        return result;
    }
}
