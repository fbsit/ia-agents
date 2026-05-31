package com.clasificacion.platformapi.catalog.dto;

import jakarta.validation.constraints.NotBlank;

public record UpdateFlowRequest(
    @NotBlank String org_id,
    @NotBlank String company_id,
    String name,
    String description,
    String graph_json,
    String status
) {
}
