package mttpe1;

import java.util.*;

public class MergeSort implements SortStrategy {

    /**
     * Sorts dates with MergeSort.
     *
     * @param input the List of Dates to be sorted
     */
    public void performSort(final List<Date> input) {
        if (input.size() > 1) {
            int mid = input.size() / 2;

            List<Date> left = new ArrayList<>(input.subList(0, mid));
            List<Date> right = new ArrayList<>(input.subList(mid, input.size()));

            performSort(left);
            performSort(right);

            merge(input, left, right);
        }
    }
    
    private void merge(List<Date> input, List<Date> left, List<Date> right) {
        int i = 0, j = 0, k = 0;

        while (i < left.size() && j < right.size()) {
            if (left.get(i).compareTo(right.get(j)) <= 0) {
                input.set(k++, left.get(i++));
            } else {
                input.set(k++, right.get(j++));
            }
        }

        while (i < left.size()) {
            input.set(k++, left.get(i++));
        }

        while (j < right.size()) {
            input.set(k++, right.get(j++));
        }
    }
}
