package de.tum.cit.aet.logos.logoswebservice.configuration.service;

import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class ModelWeightServiceUnitTest {

    private final ModelWeightService svc = new ModelWeightService(null);

    @Test
    void addFirstModel_getsWeightZero() {
        List<ModelWeightService.ModelScore> list = new ArrayList<>();
        svc.testInsertModel(list, null, 1);
        assertThat(list).hasSize(1);
        assertThat(list.get(0).score()).isEqualTo(0);
        assertThat(list.get(0).modelId()).isEqualTo(1);
    }

    @Test
    void addSecondModelAsWorst_getsNegativeWeight() {
        List<ModelWeightService.ModelScore> list = new ArrayList<>();
        list.add(new ModelWeightService.ModelScore(0, 1));
        svc.testInsertModel(list, null, 2);
        assertThat(list).hasSize(2);
        assertThat(list.get(0).modelId()).isEqualTo(2);
        assertThat(list.get(0).score()).isLessThan(list.get(1).score());
    }

    @Test
    void removeModel_reducesListByOne() {
        List<ModelWeightService.ModelScore> list = new ArrayList<>();
        list.add(new ModelWeightService.ModelScore(-4, 1));
        list.add(new ModelWeightService.ModelScore(4, 2));
        svc.testRemoveModel(list, 1);
        assertThat(list).hasSize(1);
        assertThat(list.get(0).modelId()).isEqualTo(2);
    }

    @Test
    void rankValuesToWeights_emptyMap_returnsEmpty() {
        Map<Integer, Integer> result = svc.rankValuesToWeights(Map.of());
        assertThat(result).isEmpty();
    }

    @Test
    void rankValuesToWeights_singleModel_weightZero() {
        Map<Integer, Integer> result = svc.rankValuesToWeights(Map.of(5001, 500.0));
        assertThat(result).containsEntry(5001, 0);
    }

    @Test
    void rankValuesToWeights_threeModels_bestValueGetsHighestWeight() {
        // Lower value = better (latency ms / cost $/M). 5001 is fastest.
        Map<Integer, Integer> result = svc.rankValuesToWeights(
            Map.of(5001, 500.0, 5002, 3000.0, 5003, 5000.0));
        // desc by value: 5003 (pos0 -12), 5002 (pos1 -4), 5001 (pos2 +4); median -4 -> rebalance -8/0/+8
        assertThat(result)
            .containsEntry(5003, -8)
            .containsEntry(5002, 0)
            .containsEntry(5001, 8);
        assertThat(result.get(5001)).isGreaterThan(result.get(5002)).isGreaterThan(result.get(5003));
    }

    @Test
    void rankValuesToWeights_twoModels_weightsPlusMinusFour() {
        Map<Integer, Integer> result = svc.rankValuesToWeights(
            Map.of(5001, 100.0, 5002, 900.0));
        // pos0 (5002): -8, pos1 (5001): 0; median -4 -> -4 / +4
        assertThat(result).containsEntry(5001, 4).containsEntry(5002, -4);
    }

    @Test
    void rankValuesToWeights_tiedValues_deterministicByModelId() {
        Map<Integer, Integer> result = svc.rankValuesToWeights(
            Map.of(5001, 3000.0, 5002, 3000.0, 5003, 500.0));
        // desc by value, ties broken by descending id (reversed): 5002 (pos0), 5001 (pos1), 5003 (pos2)
        // 2 distinct values -> -8/0/+8 before rebalance; median 0
        assertThat(result).containsEntry(5002, -8).containsEntry(5001, 0).containsEntry(5003, 8);
    }
}
