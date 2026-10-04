package de.tum.cit.aet.logos.logoswebservice.identity.dto;

public record StoreDeployKeyRequestDTO(
    String privateKeyPem,
    String publicKeyFingerprint
) {}
