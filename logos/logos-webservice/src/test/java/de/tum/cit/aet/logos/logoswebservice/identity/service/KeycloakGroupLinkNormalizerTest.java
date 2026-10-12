package de.tum.cit.aet.logos.logoswebservice.identity.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.util.List;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;

import de.tum.cit.aet.logos.logoswebservice.auth.KeycloakProperties;

class KeycloakGroupLinkNormalizerTest {

    private final KeycloakGroupLinkNormalizer normalizer = new KeycloakGroupLinkNormalizer(
        new KeycloakProperties(
            "logos",
            new KeycloakProperties.Roles(List.of("itg-admin"), List.of("chair-member")),
            5, null, null, null, false));

    @ParameterizedTest
    @CsvSource({
        "ios-26ws, ios-26ws",
        "/ios-26ws, ios-26ws",
        "'  /ios-26ws  ', ios-26ws",
        "/parent/ios-26ws, parent/ios-26ws",
    })
    void normalize_matchesTheClaimSpelling(String raw, String expected) {
        assertThat(normalizer.normalize(raw)).isEqualTo(expected);
    }

    @Test
    void normalize_treatsBlankAsNoLink() {
        assertThat(normalizer.normalize(null)).isNull();
        assertThat(normalizer.normalize("")).isNull();
        assertThat(normalizer.normalize("   ")).isNull();
    }

    // "/" is not an unlink: it names no group, so the caller gets told rather
    // than silently losing the team's link.
    @Test
    void normalize_rejectsAValueThatNamesNoGroup() {
        assertThatThrownBy(() -> normalizer.normalize("/"))
            .isInstanceOf(IllegalArgumentException.class);
    }

    @ParameterizedTest
    @ValueSource(strings = {"itg-admin", "chair-member", "/itg-admin"})
    void normalize_rejectsTheAdminRoles(String raw) {
        assertThatThrownBy(() -> normalizer.normalize(raw))
            .isInstanceOf(IllegalArgumentException.class);
    }

    // The sync strips the admin roles from the claim set case-sensitively, so a
    // differently cased name is a different claim and stays linkable.
    @Test
    void normalize_reservesOnlyTheConfiguredSpelling() {
        assertThat(normalizer.normalize("ITG-Admin")).isEqualTo("ITG-Admin");
    }

    @Test
    void reservedNames_areTheConfiguredAdminRoles() {
        assertThat(normalizer.reservedNames()).containsExactlyInAnyOrder("itg-admin", "chair-member");
    }
}
