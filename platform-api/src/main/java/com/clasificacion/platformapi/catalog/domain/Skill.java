package com.clasificacion.platformapi.catalog.domain;

public record Skill(
    String skillId,
    String orgId,
    String companyId,
    String name,
    String description,
    String definitionJson,
    String status,
    Integer publishedVersion
) {
}
