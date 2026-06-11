package de.tum.cit.aet.logos.logoswebservice.configuration.service;

import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;

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
}
