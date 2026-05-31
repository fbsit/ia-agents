package com.clasificacion.platformapi.catalog.dto;

import jakarta.validation.constraints.NotBlank;

public record CreateSkillRequest(
    @NotBlank String org_id,
    @NotBlank String company_id,
    @NotBlank String name,
    String description,
    String definition_json,
    String status
) {
}
