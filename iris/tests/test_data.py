# Example task descriptions and corresponding correct code submissions
# Taken from Artemis templates for programming exercises: https://github.com/ls1intum/Artemis

TASK_SORTING = """
# Sorting with the Strategy Pattern

In this exercise, we want to implement sorting algorithms and choose them based on runtime specific variables.

### Part 1: Sorting

First, we need to implement two sorting algorithms, in this case `MergeSort` and `BubbleSort`.

**You have the following tasks:**

1. [task][Implement Bubble Sort](test.behavior.BubbleSort_sorts_correctly)
   Implement the method `performSort(List<DateTime>)` in the class `BubbleSort`. Make sure to follow the Bubble Sort algorithm exactly.

2. [task][Implement Merge Sort](test.behavior.MergeSort_sorts_correctly)
   Implement the method `performSort(List<DateTime>)` in the class `MergeSort`. Make sure to follow the Merge Sort algorithm exactly.

### Part 2: Strategy Pattern

We want the application to apply different algorithms for sorting a `List` of `DateTime` objects.
Use the strategy pattern to select the right sorting algorithm at runtime.

**You have the following tasks:**

1. [task][SortStrategy Interface](test.structural.SortStrategy_class,test.structural.SortStrategy_methods,test.structural.BubbleSort_implements_SortStrategy,test.structural.MergeSort_implements_SortStrategy)
   Define the `SortStrategy` interface and adjust the sorting algorithms so that they implement this interface.

2. [task][Context Class](test.structural.Context_accessors,test.structural.Context_methods)
   Implement the `Context` class following the class diagram below

3. [task][Context Policy](test.structural.Policy_constructor,test.structural.Policy_accessors,test.structural.Policy_methods)
   Implement the `Policy` class following the class diagram below with a simple configuration mechanism:

    1. [task][Select MergeSort](test.behavior.use_MergeSort_for_big_list)
       Select `MergeSort` when the List has more than 10 dates.

    2. [task][Select BubbleSort](test.behavior.use_BubbleSort_for_small_list)
       Select `BubbleSort` when the List has less or equal 10 dates.

4. Complete the `client.dart` program which demonstrates switching between two strategies at runtime. Start it by running `dart run :client`.

@startuml

class Client {
}

class Policy {
<color:testsColor(test.structural.Policy_constructor)>Policy(Context)<<constructor>></color>
<color:testsColor(test.structural.Policy_methods)>configure()</color>
}

class Context {
<color:testsColor(test.structural.Context_accessors)>dates: List<DateTime></color>
<color:testsColor(test.structural.Context_methods)>sort()</color>
}

interface SortStrategy ##testsColor(test.structural.SortStrategy_class) {
<color:testsColor(test.structural.SortStrategy_methods)>performSort(List<DateTime>)</color>
}

class BubbleSort {
<color:testsColor(test.behavior.BubbleSort_sorts_correctly)>performSort(List<DateTime>)</color>
}

class MergeSort {
<color:testsColor(test.behavior.MergeSort_sorts_correctly)>performSort(List<DateTime>)</color>
}

MergeSort -up-|> SortStrategy #testsColor(test.structural.MergeSort_implements_SortStrategy)
BubbleSort -up-|> SortStrategy #testsColor(test.structural.BubbleSort_implements_SortStrategy)
Policy -right-> Context #testsColor(test.structural.Policy_accessors): context
Context -right-> SortStrategy #testsColor(test.structural.Context_accessors): sortAlgorithm
Client .down.> Policy
Client .down.> Context

hide empty fields
hide empty methods

@enduml


### Part 3: Optional Challenges

(These are not tested)

1. Create a new class `QuickSort` that implements `SortStrategy` and implement the Quick Sort algorithm.

2. Make the method `performSort(List<DateTime>)` generic, so that other objects can also be sorted by the same method.
   **Hint:** Have a look at Dart Generics and the interface `Comparable`.

3. Think about a useful decision in `Policy` when to use the new `QuickSort` algorithm.
"""

CODE_SORTING: dict[str, str] = {
    "src/net/java/BubbleSort.java": """package net.java;

import java.util.*;

public class BubbleSort implements SortStrategy {

    /**
     * Sorts dates with BubbleSort.
     *
     * @param input the List of Dates to be sorted
     */
    public void performSort(List<Date> input) {

        for (int i = input.size() - 1; i >= 0; i--) {
            for (int j = 0; j < i; j++) {
                if (input.get(j).compareTo(input.get(j + 1)) > 0) {
                    Date temp = input.get(j);
                    input.set(j, input.get(j + 1));
                    input.set(j + 1, temp);
                }
            }
        }

    }
}
""",

    "src/net/java/Client.java": """package net.java;

import java.text.*;
import java.util.*;
import java.util.concurrent.ThreadLocalRandom;

public final class Client {

    private static final int ITERATIONS = 10;

    private static final int RANDOM_FLOOR = 5;

    private static final int RANDOM_CEILING = 15;

    private Client() {
    }

    /**
     * Main method.
     * Add code to demonstrate your implementation here.
     *
     * @param args command line arguments
     */
    public static void main(String[] args) throws ParseException {

        // Init Context and Policy

        Context sortingContext = new Context();
        Policy policy = new Policy(sortingContext);

        // Run multiple times to simulate different sorting strategies
        for (int i = 0; i < ITERATIONS; i++) {
            List<Date> dates = createRandomDatesList();

            sortingContext.setDates(dates);
            policy.configure();

            System.out.print("Unsorted Array of course dates = ");
            printDateList(dates);

            sortingContext.sort();

            System.out.print("Sorted Array of course dates = ");
            printDateList(dates);
        }
    }

    /**
     * Generates a List of random Date objects with random List size between
     * {@link #RANDOM_FLOOR} and {@link #RANDOM_CEILING}.
     *
     * @return a List of random Date objects
     * @throws ParserException if date string cannot be parsed
     */
    private static List<Date> createRandomDatesList() throws ParseException {
        int listLength = randomIntegerWithin(RANDOM_FLOOR, RANDOM_CEILING);
        List<Date> list = new ArrayList<>();

        SimpleDateFormat dateFormat = new SimpleDateFormat("dd.MM.yyyy");
        Date lowestDate = dateFormat.parse("08.11.2016");
        Date highestDate = dateFormat.parse("03.11.2020");

        for (int i = 0; i < listLength; i++) {
            Date randomDate = randomDateWithin(lowestDate, highestDate);
            list.add(randomDate);
        }
        return list;
    }

    private static Date randomDateWithin(Date low, Date high) {
        long randomLong = randomLongWithin(low.getTime(), high.getTime());
        return new Date(randomLong);
    }

    private static long randomLongWithin(long low, long high) {
        return ThreadLocalRandom.current().nextLong(low, high + 1);
    }

    private static int randomIntegerWithin(int low, int high) {
        return ThreadLocalRandom.current().nextInt(low, high + 1);
    }

    private static void printDateList(List<Date> list) {
        System.out.println(list.toString());
    }
}
""",

    "src/net/java/Context.java": """package net.java;

import java.util.*;

public class Context {
    private SortStrategy sortAlgorithm;

    private List<Date> dates;

    public List<Date> getDates() {
        return dates;
    }

    public void setDates(List<Date> dates) {
        this.dates = dates;
    }

    public void setSortAlgorithm(SortStrategy sa) {
        sortAlgorithm = sa;
    }

    public SortStrategy getSortAlgorithm() {
        return sortAlgorithm;
    }

    public void sort() {
        if (sortAlgorithm != null) {
            sortAlgorithm.performSort(this.dates);
        }
    }
}
""",

    "src/net/java/MergeSort.java": """package net.java;

import java.util.*;

public class MergeSort implements SortStrategy {

    public void performSort(List<Date> input) {
        mergesort(input, 0, input.size() - 1);
    }

    private void mergesort(List<Date> input, int low, int high) {
        if (high - low < 1) {
            return;
        }
        int mid = (low + high) / 2;
        mergesort(input, low, mid);
        mergesort(input, mid + 1, high);
        merge(input, low, mid, high);
    }

    private void merge(List<Date> input, int low, int middle, int high) {

        Date[] temp = new Date[high - low + 1];
        int leftIndex = low;
        int rightIndex = middle + 1;
        int wholeIndex = 0;
        while (leftIndex <= middle && rightIndex <= high) {
            if (input.get(leftIndex).compareTo(input.get(rightIndex)) <= 0) {
                temp[wholeIndex] = input.get(leftIndex++);
            }
            else {
                temp[wholeIndex] = input.get(rightIndex++);
            }
            wholeIndex++;
        }
        if (leftIndex <= middle && rightIndex > high) {
            while (leftIndex <= middle) {
                temp[wholeIndex++] = input.get(leftIndex++);
            }
        }
        else {
            while (rightIndex <= high) {
                temp[wholeIndex++] = input.get(rightIndex++);
            }
        }
        for (wholeIndex = 0; wholeIndex < temp.length; wholeIndex++) {
            input.set(wholeIndex + low, temp[wholeIndex]);
        }
    }
}
""",

    "src/net/java/Policy.java": """package net.java;

public class Policy {

    private static final int DATES_SIZE_THRESHOLD = 10;

    private Context context;

    public Policy(Context context) {
        this.context = context;
    }

    public void configure() {
        if (this.context.getDates().size() > DATES_SIZE_THRESHOLD) {
            System.out.println("More than " + DATES_SIZE_THRESHOLD
                + " dates, choosing merge sort!");
            this.context.setSortAlgorithm(new MergeSort());
        } else {
            System.out.println("Less or equal than " + DATES_SIZE_THRESHOLD
                + " dates. choosing quick sort!");
            this.context.setSortAlgorithm(new BubbleSort());
        }
    }
}
""",

    "src/net/java/SortStrategy.java": """package net.java;

import java.util.Date;
import java.util.List;

public interface SortStrategy {

    void performSort(List<Date> input);
}
"""
}


TEMPLATE_SORTING : dict[str, str] = {
    "src/net/java/BubbleSort.java": """package net.java;

import java.util.*;

public class BubbleSort {

    /**
     * Sorts dates with BubbleSort.
     *
     * @param input the List of Dates to be sorted
     */
    public void performSort(final List<Date> input) {

        //TODO: implement
    }
}
""",

    "src/net/java/Client.java": """package net.java;

import java.text.*;
import java.util.*;
import java.util.concurrent.ThreadLocalRandom;

public final class Client {

    // TODO: Implement BubbleSort
    // TODO: Implement MergeSort

    // TODO: Create a SortStrategy interface according to the UML class diagram
    // TODO: Make the sorting algorithms implement this interface.

    // TODO: Create and implement a Context class according to the UML class diagram
    // TODO: Create and implement a Policy class as described in the problem statement

    private static final int ITERATIONS = 10;

    private static final int RANDOM_FLOOR = 5;

    private static final int RANDOM_CEILING = 15;

    private Client() {
    }

    /**
     * Main method.
     * Add code to demonstrate your implementation here.
     *
     * @param args command line arguments
     */
    public static void main(String[] args) throws ParseException {

        // TODO: Init Context and Policy

        // Run multiple times to simulate different sorting strategies for different Array sizes
        for (int i = 0; i < ITERATIONS; i++) {
            List<Date> dates = createRandomDatesList();

            // TODO: Configure context

            System.out.print("Unsorted Array of course dates = ");
            printDateList(dates);

            // TODO: Sort dates

            System.out.print("Sorted Array of course dates = ");
            printDateList(dates);
        }
    }

    private static List<Date> createRandomDatesList() throws ParseException {
        int listLength = randomIntegerWithin(RANDOM_FLOOR, RANDOM_CEILING);
        List<Date> list = new ArrayList<>();

        SimpleDateFormat dateFormat = new SimpleDateFormat("dd.MM.yyyy");
        Date lowestDate = dateFormat.parse("08.11.2016");
        Date highestDate = dateFormat.parse("03.11.2020");

        for (int i = 0; i < listLength; i++) {
            Date randomDate = randomDateWithin(lowestDate, highestDate);
            list.add(randomDate);
        }
        return list;
    }

    private static Date randomDateWithin(Date low, Date high) {
        long randomLong = randomLongWithin(low.getTime(), high.getTime());
        return new Date(randomLong);
    }

    private static long randomLongWithin(long low, long high) {
        return ThreadLocalRandom.current().nextLong(low, high + 1);
    }

    private static int randomIntegerWithin(int low, int high) {
        return ThreadLocalRandom.current().nextInt(low, high + 1);
    }

    private static void printDateList(List<Date> list) {
        System.out.println(list.toString());
    }
}
""",

    "src/net/java/MergeSort.java": """package net.java;

import java.util.*;

public class MergeSort {

    /**
     * Sorts dates with MergeSort.
     *
     * @param input the List of Dates to be sorted
     */
    public void performSort(final List<Date> input) {

        //TODO: implement
    }

}
"""
}

LLM_EVALUATION_PROMPT = ""