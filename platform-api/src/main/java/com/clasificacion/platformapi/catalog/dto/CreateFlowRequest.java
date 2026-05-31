package com.clasificacion.platformapi.catalog.dto;

import jakarta.validation.constraints.NotBlank;

public record CreateFlowRequest(
    @NotBlank String org_id,
    @NotBlank String company_id,
    @NotBlank String name,
    String description,
    String graph_json,
    String status
) {
}
