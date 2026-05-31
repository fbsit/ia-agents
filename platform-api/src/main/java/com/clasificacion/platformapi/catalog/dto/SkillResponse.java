package com.clasificacion.platformapi.catalog.dto;

public record SkillResponse(
    String skill_id,
    String org_id,
    String company_id,
    String name,
    String description,
    String definition_json,
    String status,
    Integer published_version
) {
}
