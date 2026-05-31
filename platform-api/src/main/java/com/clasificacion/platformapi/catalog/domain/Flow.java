package com.clasificacion.platformapi.catalog.domain;

public record Flow(
    String flowId,
    String orgId,
    String companyId,
    String name,
    String description,
    String graphJson,
    String status,
    Integer publishedVersion
) {
}
