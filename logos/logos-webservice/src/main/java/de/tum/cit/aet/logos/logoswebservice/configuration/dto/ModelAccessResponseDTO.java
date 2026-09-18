package de.tum.cit.aet.logos.logoswebservice.configuration.dto;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;

/**
 * Read-only snapshot of who can actually reach a single model.
 *
 * <p>Grants are two independent dimensions (model, provider), so a grant
 * only means anything when both sides line up: {@code effectiveAccess} is
 * the model grant AND at least one grant on a hosting provider. Teams or
 * keys with a model grant but no grant for any hosting provider are
 * orphaned — the model can never route for them — and that is exactly the
 * state the per-team permission views cannot surface.
 */
public record ModelAccessResponseDTO(
        ModelDTO model,
        List<HostingProviderDTO> providers,
        List<TeamAccessDTO> teams,
        List<KeyAccessDTO> apiKeys) {

    public record ModelDTO(
            Integer id,
            String name,
            String description,
            String tags,
            List<String> aliases,
            BigDecimal inputUsdPerMillion,
            BigDecimal outputUsdPerMillion,
            Integer maxInputTokens,
            Instant lastUsedAt) {}

    public record HostingProviderDTO(
            Integer providerId,
            String name,
            String providerType,
            String privacyLevel,
            Long requestCount,
            Instant lastRequestAt) {}

    public record TeamAccessDTO(
            Integer teamId,
            String teamName,
            boolean modelGrant,
            List<ProviderGrantDTO> providerGrants,
            boolean effectiveAccess) {}

    public record KeyAccessDTO(
            Integer keyId,
            String keyName,
            Boolean isActive,
            Integer teamId,
            String teamName,
            boolean modelGrant,
            List<ProviderGrantDTO> providerGrants,
            boolean effectiveAccess) {}

    /** Grant state of one key/team for a single hosting provider of the model. */
    public record ProviderGrantDTO(Integer providerId, boolean granted) {}
}
