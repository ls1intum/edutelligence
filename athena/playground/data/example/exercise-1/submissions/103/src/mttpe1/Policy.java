package mttpe1;

import java.util.*;

public class Policy {
    private Context context;

    public Policy(Context context) {
        this.context = context;
    }

    public void configure() {
        List<Date> dates = context.getDates();
        if (dates.size() > 10) {
            context.setSortAlgorithm(new MergeSort());
        } else {
            context.setSortAlgorithm(new BubbleSort());
        }
    }
}