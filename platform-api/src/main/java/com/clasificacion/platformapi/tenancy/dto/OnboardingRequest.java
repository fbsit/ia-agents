package com.clasificacion.platformapi.tenancy.dto;

import jakarta.validation.constraints.NotBlank;

public record OnboardingRequest(
    @NotBlank String organization_name,
    String company_id
) {
}
