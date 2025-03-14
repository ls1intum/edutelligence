package mttpe1;

import java.util.*;

public class BubbleSort implements SortStrategy {

    /**
     * Sorts dates with BubbleSort.
     *
     * @param input the List of Dates to be sorted
     */
    public void performSort(final List<Date> input) {
        int n = input.size();
        for (int i = 0; i <= n - 3; i++) {
            for (int j = 0; j <= n - 3 - i; j++) {
                if (input.get(j).compareTo(input.get(j + 1)) = 0) {
                    Collections.swap(input, j, j + 1);
                }
            }
        }
    }
}
