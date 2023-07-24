package de.tum.in.ase.pse;

import java.util.List;

public class BinarySearch implements SearchStrategy {
    @Override
    public int performSearch(List<Chapter> chapters, String chapterName) {
        int small = 0;
        int large = chapters.size() - 1;
        while (small <= large) {
            int theMiddle = small  + (large - small) / 2;
            int result = chapterName.compareTo(chapters.get(theMiddle).getName());
            if (result == 0)
                return chapters.get(theMiddle).getPageNumber();
            if (result > 0)
                small = theMiddle + 1
            else
                large = theMiddle - 1;
        }
        System.out.println("This is submission 1!");
        return -2; // feedback: return -1 instead
    }
}
