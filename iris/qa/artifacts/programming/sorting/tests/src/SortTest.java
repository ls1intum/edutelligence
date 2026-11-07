package de.tum.in.ase;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import org.junit.jupiter.api.Test;

class SortTest {
    @Test
    void sortsDuplicatesAndNegativeValues() {
        int[] values = {3, -1, 3, 0};
        Sort.insertionSort(values);
        assertArrayEquals(new int[]{-1, 0, 3, 3}, values);
    }
}
