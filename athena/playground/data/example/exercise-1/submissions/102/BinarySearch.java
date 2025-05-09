package de.tum.in.ase.pse;

import java.util.List;

public class BinarySearch implements SearchStrategy {
    @Override
    public int performSearch(List<Chapter> chapters, String chapterName) {
        int low = 0;
        int high = chapters.size() - 1
        while (low <= high) {
            int mid = (low + high) / 2;
            int comparison = chapters.get(mid).getName().compareTo(chapterName);
            if (comparison < 0) {
                low = mid + 1;
            } else if (comparison > 0) {
                high = mid - 1;
            } else {
                return mid;
            }
        }
        return -2;
    }
}
