package de.tum.cit.aet.logos.logoswebservice.identity;

import java.util.ArrayList;
import java.util.List;

public final class Csv {

    private Csv() {}

    public static List<String[]> parse(String content) {
        List<String[]> rows = new ArrayList<>();
        if (content == null) return rows;
        List<String> row = new ArrayList<>();
        StringBuilder field = new StringBuilder();
        boolean inQuotes = false;
        boolean fieldTouched = false;
        for (int i = 0; i < content.length(); i++) {
            char c = content.charAt(i);
            if (inQuotes) {
                if (c == '"') {
                    if (i + 1 < content.length() && content.charAt(i + 1) == '"') {
                        field.append('"');
                        i++;
                    } else {
                        inQuotes = false;
                    }
                } else {
                    field.append(c);
                }
                fieldTouched = true;
            } else if (c == '"' && !fieldTouched) {
                inQuotes = true;
                fieldTouched = true;
            } else if (c == ',') {
                row.add(field.toString());
                field.setLength(0);
                fieldTouched = false;
            } else if (c == '\r' || c == '\n') {
                if (c == '\r' && i + 1 < content.length() && content.charAt(i + 1) == '\n') {
                    i++;
                }
                row.add(field.toString());
                field.setLength(0);
                fieldTouched = false;
                commitRow(row, rows);
                row = new ArrayList<>();
            } else {
                field.append(c);
                fieldTouched = true;
            }
        }
        if (fieldTouched || !row.isEmpty()) {
            row.add(field.toString());
            commitRow(row, rows);
        }
        return rows;
    }

    private static void commitRow(List<String> row, List<String[]> rows) {
        boolean blank = row.size() == 1 && row.get(0).isEmpty();
        if (!blank) {
            rows.add(row.toArray(new String[0]));
        }
    }
}
