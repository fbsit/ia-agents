package com.clasificacion.platformapi.catalog.dto;

public record PublishResponse(
    String id,
    String type,
    int published_version,
    String status
) {
}
