package de.tum.cit.aet.logos.logoswebservice.configuration.service;

import de.tum.cit.aet.logos.logoswebservice.configuration.entity.Model;
import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

class ModelWeightServiceUnitTest {

    private final ModelWeightService svc = new ModelWeightService(null, null);

    @Test
    void addFirstModel_getsWeightZero() {
        List<int[]> list = new ArrayList<>();
        svc.testAddModel(list, null, 1);
        assertThat(list).hasSize(1);
        assertThat(list.get(0)[0]).isEqualTo(0);
        assertThat(list.get(0)[1]).isEqualTo(1);
    }

    @Test
    void addSecondModelAsWorst_getsNegativeWeight() {
        List<int[]> list = new ArrayList<>();
        list.add(new int[]{0, 1});
        svc.testAddModel(list, null, 2);
        assertThat(list).hasSize(2);
        assertThat(list.get(0)[1]).isEqualTo(2);
        assertThat(list.get(0)[0]).isLessThan(list.get(1)[0]);
    }

    @Test
    void removeModel_reducesListByOne() {
        List<int[]> list = new ArrayList<>();
        list.add(new int[]{-4, 1});
        list.add(new int[]{4, 2});
        svc.testRemoveModel(list, 1);
        assertThat(list).hasSize(1);
        assertThat(list.get(0)[1]).isEqualTo(2);
    }
}
