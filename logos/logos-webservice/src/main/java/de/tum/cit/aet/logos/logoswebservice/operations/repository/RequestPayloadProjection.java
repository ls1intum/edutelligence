package de.tum.cit.aet.logos.logoswebservice.operations.repository;

/** Content fetched only when an administrator opens a request's details. */
public interface RequestPayloadProjection {
    String getInputPayload();
    String getResponsePayload();
}
