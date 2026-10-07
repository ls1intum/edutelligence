package de.tum.cit.aet.logos.logoswebservice.identity.service;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.List;
import java.util.Map;

import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockMultipartFile;

class UserServicePreviewImportTest {

    @Test
    void previewImport_returns_header_row_as_flat_column_list() throws Exception {
        String csv = "First Name,Last Name,Email\nTobias,Wasner,tobias.wasner@tum.de\n";
        UserService service = new UserService(null, null, null);

        Map<String, Object> result = service.previewImport(
            new MockMultipartFile("file", "people.csv", "text/csv", csv.getBytes()));

        // The web application labels its mapping selects with the column
        // names, so `columns` must be a flat list of strings — a nested list
        // would serialize as an array of arrays and break the preview.
        List<?> columns = (List<?>) result.get("columns");
        assertThat(columns).isEqualTo(List.of("First Name", "Last Name", "Email"));
        assertThat(columns.get(0)).isInstanceOf(String.class);
        assertThat(result.get("rows")).isEqualTo(List.of(List.of("Tobias", "Wasner", "tobias.wasner@tum.de")));
    }

    @Test
    void previewImport_returns_empty_lists_for_a_file_without_rows() throws Exception {
        UserService service = new UserService(null, null, null);

        Map<String, Object> result = service.previewImport(
            new MockMultipartFile("file", "empty.csv", "text/csv", new byte[0]));

        assertThat(result.get("columns")).isEqualTo(List.of());
        assertThat(result.get("rows")).isEqualTo(List.of());
    }
}
