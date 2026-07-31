package edu.tum.events;

public record Event(String partition, String eventId, long timestampMillis) {}
