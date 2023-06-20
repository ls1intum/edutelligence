package mttpe1;

import java.util.*;

public class Context {
    private List<Date> dates;
    private SortStrategy sortAlgorithm;

    public Context(List<Date> dates) {
        this.dates = dates;
    }

    public void setSortAlgorithm(SortStrategy sortAlgorithm) {
        this.sortAlgorithm = sortAlgorithm;
    }

    public void sort() {
        sortAlgorithm.performSort(dates);
    }

    public List<Date> getDates() {
        return dates;
    }
}