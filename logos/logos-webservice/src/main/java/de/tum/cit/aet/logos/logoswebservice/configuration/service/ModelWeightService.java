package de.tum.cit.aet.logos.logoswebservice.configuration.service;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import de.tum.cit.aet.logos.logoswebservice.configuration.entity.Model;
import de.tum.cit.aet.logos.logoswebservice.configuration.repository.ModelRepository;

@Service
public class ModelWeightService {

    private static final int BASE_FEEDBACK = 2;
    private static final int FEEDBACK_SCALE = 2;

    private final ModelRepository modelRepository;

    record ModelScore(int score, int modelId) {
        ModelScore withScore(int newScore) {
            return new ModelScore(newScore, modelId);
        }
    }

    public ModelWeightService(ModelRepository modelRepository) {
        this.modelRepository = modelRepository;
    }

    @Transactional
    public void rebalanceAfterAdd(int newModelId, Integer worseLatencyId, Integer worseAccuracyId,
                                   Integer worseCostId, Integer worseQualityId) {
        List<Model> allModels = modelRepository.findAll();
        List<ModelScore> latencyRankings  = sortedByDimension(allModels, "latency",  newModelId);
        List<ModelScore> accuracyRankings = sortedByDimension(allModels, "accuracy", newModelId);
        List<ModelScore> costRankings     = sortedByDimension(allModels, "cost",     newModelId);
        List<ModelScore> qualityRankings  = sortedByDimension(allModels, "quality",  newModelId);
        insertModel(latencyRankings,  worseLatencyId,  newModelId);
        insertModel(accuracyRankings, worseAccuracyId, newModelId);
        insertModel(costRankings,     worseCostId,     newModelId);
        insertModel(qualityRankings,  worseQualityId,  newModelId);
        persistWeights(latencyRankings, accuracyRankings, costRankings, qualityRankings);
    }

    @Transactional
    public void rebalanceAfterFeedback(int modelId, String category, int feedback) {
        if (!java.util.Set.of("latency", "accuracy", "cost", "quality").contains(category)) {
            throw new IllegalArgumentException("Invalid category: " + category);
        }
        List<Model> allModels = modelRepository.findAll();
        List<ModelScore> rankings = sortedByDimension(allModels, category, -1);

        int position = indexOf(rankings, modelId);
        if (position == -1) throw new IllegalArgumentException("Model not found: " + modelId);

        rankings.set(position, rankings.get(position).withScore(rankings.get(position).score() + feedback));

        int uniqueScoreCount = countUnique(rankings);
        ModelScore[] normalizedScores = normalizeScores(rankings, uniqueScoreCount);
        int[] scoreDiffs = new int[rankings.size()];
        for (int i = 0; i < rankings.size(); i++) {
            scoreDiffs[i] = normalizedScores[i].score() - rankings.get(i).score();
        }

        while (position > 0 && rankings.get(position).score() < rankings.get(position - 1).score()) {
            ModelScore displaced = rankings.get(position);
            rankings.set(position, rankings.get(position - 1));
            rankings.set(position - 1, displaced);
            rankings.set(position, rankings.get(position).withScore(normalizedScores[position].score() - scoreDiffs[position - 1]));
            position--;
        }
        while (position < rankings.size() - 1 && rankings.get(position).score() > rankings.get(position + 1).score()) {
            ModelScore displaced = rankings.get(position);
            rankings.set(position, rankings.get(position + 1));
            rankings.set(position + 1, displaced);
            rankings.set(position, rankings.get(position).withScore(normalizedScores[position].score() - scoreDiffs[position + 1]));
            position++;
        }

        ModelScore[] balanced = rebalance(rankings.toArray(new ModelScore[0]));
        for (int i = 0; i < rankings.size(); i++) {
            rankings.set(i, balanced[i]);
        }

        List<Integer> modelIds = rankings.stream().map(ModelScore::modelId).toList();
        Map<Integer, Model> modelMap = modelRepository.findAllById(modelIds).stream()
            .collect(Collectors.toMap(Model::getId, m -> m));
        for (ModelScore entry : rankings) {
            Model model = modelMap.get(entry.modelId());
            if (model == null) continue;
            switch (category) {
                case "latency"  -> model.setWeightLatency(entry.score());
                case "accuracy" -> model.setWeightAccuracy(entry.score());
                case "cost"     -> model.setWeightCost(entry.score());
                case "quality"  -> model.setWeightQuality(entry.score());
                default -> throw new IllegalArgumentException("Invalid category: " + category);
            }
        }
        modelRepository.saveAll(modelMap.values());
    }

    @Transactional
    public void rebalanceAfterDelete(int deletedModelId) {
        List<Model> allModels = modelRepository.findAll();
        List<ModelScore> latencyRankings  = sortedByDimension(allModels, "latency",  -1);
        List<ModelScore> accuracyRankings = sortedByDimension(allModels, "accuracy", -1);
        List<ModelScore> costRankings     = sortedByDimension(allModels, "cost",     -1);
        List<ModelScore> qualityRankings  = sortedByDimension(allModels, "quality",  -1);
        removeModel(latencyRankings,  deletedModelId);
        removeModel(accuracyRankings, deletedModelId);
        removeModel(costRankings,     deletedModelId);
        removeModel(qualityRankings,  deletedModelId);
        persistWeights(latencyRankings, accuracyRankings, costRankings, qualityRankings);
        modelRepository.deleteById(deletedModelId);
    }

    void testInsertModel(List<ModelScore> list, Integer worseId, int newId) {
        insertModel(list, worseId, newId);
    }

    void testRemoveModel(List<ModelScore> list, int modelId) {
        removeModel(list, modelId);
    }

    private List<ModelScore> sortedByDimension(List<Model> models, String dimension, int excludeId) {
        return models.stream()
            .filter(model -> !model.getId().equals(excludeId))
            .map(model -> new ModelScore(dimensionWeight(model, dimension), model.getId()))
            .sorted(Comparator.comparingInt(ModelScore::score))
            .collect(Collectors.toCollection(ArrayList::new));
    }

    private int dimensionWeight(Model model, String dimension) {
        return switch (dimension) {
            case "latency"  -> model.getWeightLatency()  != null ? model.getWeightLatency()  : 0;
            case "accuracy" -> model.getWeightAccuracy() != null ? model.getWeightAccuracy() : 0;
            case "cost"     -> model.getWeightCost()     != null ? model.getWeightCost()     : 0;
            case "quality"  -> model.getWeightQuality()  != null ? model.getWeightQuality()  : 0;
            default -> 0;
        };
    }

    private void insertModel(List<ModelScore> rankings, Integer worseModelId, int newModelId) {
        int insertPosition;
        if (worseModelId == null) {
            insertPosition = 0;
        } else {
            int worsePosition = indexOf(rankings, worseModelId);
            insertPosition = (worsePosition == -1) ? 0 : worsePosition + 1;
        }

        int uniqueScoreCountBefore = countUnique(rankings);
        ModelScore newEntry = new ModelScore(computeScore(0, uniqueScoreCountBefore), newModelId);

        ModelScore[] normalizedScores = normalizeScores(rankings, uniqueScoreCountBefore);
        int[] scoreDiffs = new int[rankings.size()];
        for (int i = 0; i < rankings.size(); i++) {
            scoreDiffs[i] = normalizedScores[i].score() - rankings.get(i).score();
        }

        int midScore = rankings.size() >= 2
            ? (rankings.get(0).score() + rankings.get(rankings.size() - 1).score()) / 2
            : 0;

        if (insertPosition >= rankings.size()) {
            rankings.add(newEntry);
            scoreDiffs = appendInt(scoreDiffs, -midScore);
        } else {
            rankings.add(insertPosition, newEntry);
            scoreDiffs = insertInt(scoreDiffs, insertPosition, -midScore);
        }

        int uniqueScoreCountAfter = countUnique(rankings);
        ModelScore[] adjustedScores = normalizeScores(rankings, uniqueScoreCountAfter);
        for (int i = 0; i < adjustedScores.length; i++) {
            adjustedScores[i] = adjustedScores[i].withScore(adjustedScores[i].score() - scoreDiffs[i]);
        }
        ModelScore[] finalScores = rebalance(adjustedScores);
        for (int i = 0; i < rankings.size(); i++) {
            rankings.set(i, finalScores[i]);
        }
    }

    private void removeModel(List<ModelScore> rankings, int modelIdToRemove) {
        int uniqueScoreCountBefore = countUnique(rankings);
        ModelScore[] normalizedScores = normalizeScores(rankings, uniqueScoreCountBefore);
        int[] scoreDiffs = new int[rankings.size()];
        for (int i = 0; i < rankings.size(); i++) {
            scoreDiffs[i] = normalizedScores[i].score() - rankings.get(i).score();
        }

        int position = indexOf(rankings, modelIdToRemove);
        if (position == -1) return;
        rankings.remove(position);
        scoreDiffs = removeInt(scoreDiffs, position);

        if (rankings.isEmpty()) return;

        int uniqueScoreCountAfter = countUnique(rankings);
        ModelScore[] adjustedScores = normalizeScores(rankings, uniqueScoreCountAfter);
        for (int i = 0; i < adjustedScores.length; i++) {
            adjustedScores[i] = adjustedScores[i].withScore(adjustedScores[i].score() - scoreDiffs[i]);
        }
        ModelScore[] finalScores = rebalance(adjustedScores);
        for (int i = 0; i < rankings.size(); i++) {
            rankings.set(i, finalScores[i]);
        }
    }

    private ModelScore[] normalizeScores(List<ModelScore> rankings, int uniqueScoreCount) {
        ModelScore[] scored = new ModelScore[rankings.size()];
        for (int i = 0; i < rankings.size(); i++) {
            scored[i] = new ModelScore(computeScore(i, uniqueScoreCount), rankings.get(i).modelId());
        }
        return rebalance(scored);
    }

    private int computeScore(int position, int uniqueScoreCount) {
        if (uniqueScoreCount == 0) return 0;
        return FEEDBACK_SCALE * (-BASE_FEEDBACK * uniqueScoreCount + 2 * BASE_FEEDBACK * position);
    }

    private ModelScore[] rebalance(ModelScore[] rankings) {
        if (rankings.length == 0) return rankings;
        int count = rankings.length;
        int median = ((count & 1) == 1)
            ? rankings[count / 2].score()
            : (rankings[count / 2 - 1].score() + rankings[count / 2].score()) / 2;
        ModelScore[] result = new ModelScore[count];
        for (int i = 0; i < count; i++) {
            result[i] = new ModelScore(rankings[i].score() - median, rankings[i].modelId());
        }
        return result;
    }

    private int indexOf(List<ModelScore> rankings, int modelId) {
        for (int i = 0; i < rankings.size(); i++) {
            if (rankings.get(i).modelId() == modelId) return i;
        }
        return -1;
    }

    private int countUnique(List<ModelScore> rankings) {
        return (int) rankings.stream().mapToInt(ModelScore::score).distinct().count();
    }

    private void persistWeights(List<ModelScore> latency, List<ModelScore> accuracy,
                                 List<ModelScore> cost, List<ModelScore> quality) {
        Map<Integer, int[]> weightsByModelId = new HashMap<>();
        for (ModelScore entry : latency)   weightsByModelId.computeIfAbsent(entry.modelId(), k -> new int[4])[0] = entry.score();
        for (ModelScore entry : accuracy)  weightsByModelId.computeIfAbsent(entry.modelId(), k -> new int[4])[1] = entry.score();
        for (ModelScore entry : cost)      weightsByModelId.computeIfAbsent(entry.modelId(), k -> new int[4])[2] = entry.score();
        for (ModelScore entry : quality)   weightsByModelId.computeIfAbsent(entry.modelId(), k -> new int[4])[3] = entry.score();
        List<Integer> ids = new ArrayList<>(weightsByModelId.keySet());
        Map<Integer, Model> modelMap = modelRepository.findAllById(ids).stream()
            .collect(Collectors.toMap(Model::getId, m -> m));
        for (Map.Entry<Integer, int[]> entry : weightsByModelId.entrySet()) {
            Model model = modelMap.get(entry.getKey());
            if (model == null) continue;
            int[] w = entry.getValue();
            model.setWeightLatency(w[0]);
            model.setWeightAccuracy(w[1]);
            model.setWeightCost(w[2]);
            model.setWeightQuality(w[3]);
        }
        modelRepository.saveAll(modelMap.values());
    }

    private int[] appendInt(int[] values, int value) {
        int[] result = Arrays.copyOf(values, values.length + 1);
        result[values.length] = value;
        return result;
    }

    private int[] insertInt(int[] values, int position, int value) {
        int[] result = new int[values.length + 1];
        System.arraycopy(values, 0, result, 0, position);
        result[position] = value;
        System.arraycopy(values, position, result, position + 1, values.length - position);
        return result;
    }

    private int[] removeInt(int[] values, int position) {
        int[] result = new int[values.length - 1];
        System.arraycopy(values, 0, result, 0, position);
        System.arraycopy(values, position + 1, result, position, values.length - position - 1);
        return result;
    }
}
