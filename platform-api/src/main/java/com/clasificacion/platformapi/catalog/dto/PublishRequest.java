package com.clasificacion.platformapi.catalog.dto;

import jakarta.validation.constraints.NotBlank;

public record PublishRequest(
    @NotBlank String org_id,
    @NotBlank String company_id
) {
}
