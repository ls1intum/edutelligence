package de.tum.cit.aet.logos.logoswebservice.identity.service;

import java.security.SecureRandom;
import java.util.Base64;

import org.springframework.stereotype.Component;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKey;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKeyType;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.LogLevel;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.Team;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.User;

@Component
public class ApiKeyFactory {

    private static final SecureRandom SECURE_RANDOM = new SecureRandom();

    public static String generateToken() {
        byte[] bytes = new byte[96];
        SECURE_RANDOM.nextBytes(bytes);
        return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
    }

    public ApiKey createDeveloperKey(User user, Team team) {
        String userSlug = toSlug(user.getUsername());
        String label = team != null
            ? (toSlug(team.getName()) + "-" + userSlug)
            : userSlug;
        if (label.length() > 35) label = label.substring(0, 35);

        ApiKey key = new ApiKey();
        key.setKeyValue("lg-" + label + "-" + generateToken());
        key.setName(team != null
            ? (user.getUsername() + "-" + team.getName() + "-key")
            : (user.getUsername() + "-personal-key"));
        key.setKeyType(ApiKeyType.developer);
        key.setTeamId(team != null ? team.getId() : null);
        key.setUserId(user.getId());
        key.setEnvironment("-");
        key.setLog(LogLevel.BILLING);
        key.setSettings("{}");
        key.setDefaultPriority(1);
        key.setIsActive(true);
        key.setUseCustomPermissions(false);
        return key;
    }

    private static String toSlug(String name) {
        return name.toLowerCase()
            .replaceAll("[^a-z0-9\\-]", "-")
            .replaceAll("\\-+", "-")
            .replaceAll("^\\-|\\-$", "");
    }
}
