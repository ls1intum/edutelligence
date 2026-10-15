package de.tum.cit.aet.logos.logoswebservice.identity;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;

import org.junit.jupiter.api.Test;

class CsvTest {

    @Test
    void parsesHeaderAndRows() {
        List<String[]> rows = Csv.parse("First Name,Last Name,Email\nAlice,Smith,alice@example.com\n");
        assertEquals(2, rows.size());
        assertArrayEquals(new String[] { "First Name", "Last Name", "Email" }, rows.get(0));
        assertArrayEquals(new String[] { "Alice", "Smith", "alice@example.com" }, rows.get(1));
    }

    @Test
    void handlesNoTrailingNewline() {
        List<String[]> rows = Csv.parse("a,b\n1,2");
        assertEquals(2, rows.size());
        assertArrayEquals(new String[] { "a", "b" }, rows.get(0));
        assertArrayEquals(new String[] { "1", "2" }, rows.get(1));
    }

    @Test
    void keepsEmbeddedCommasInQuotedFields() {
        List<String[]> rows = Csv.parse("\"he, said\",x\n");
        assertEquals(1, rows.size());
        assertArrayEquals(new String[] { "he, said", "x" }, rows.get(0));
    }

    @Test
    void unescapesDoubledQuotes() {
        List<String[]> rows = Csv.parse("\"he said \"\"hi\"\"\"\n");
        assertEquals(1, rows.size());
        assertArrayEquals(new String[] { "he said \"hi\"" }, rows.get(0));
    }

    @Test
    void keepsEmbeddedNewlineInQuotedField() {
        List<String[]> rows = Csv.parse("\"a\nb\",c\n");
        assertEquals(1, rows.size());
        assertArrayEquals(new String[] { "a\nb", "c" }, rows.get(0));
    }

    @Test
    void preservesEmptyFields() {
        List<String[]> rows = Csv.parse("a,,c\n");
        assertEquals(1, rows.size());
        assertArrayEquals(new String[] { "a", "", "c" }, rows.get(0));
    }

    @Test
    void handlesCrLfLineEndings() {
        List<String[]> rows = Csv.parse("a,b\r\n1,2\r\n");
        assertEquals(2, rows.size());
        assertArrayEquals(new String[] { "a", "b" }, rows.get(0));
        assertArrayEquals(new String[] { "1", "2" }, rows.get(1));
    }

    @Test
    void skipsBlankLines() {
        List<String[]> rows = Csv.parse("a,b\n\n1,2\n");
        assertEquals(2, rows.size());
        assertArrayEquals(new String[] { "a", "b" }, rows.get(0));
        assertArrayEquals(new String[] { "1", "2" }, rows.get(1));
    }

    @Test
    void returnsNothingForBlankContent() {
        assertTrue(Csv.parse("").isEmpty());
        assertTrue(Csv.parse("\n").isEmpty());
        assertTrue(Csv.parse(null).isEmpty());
    }
}
