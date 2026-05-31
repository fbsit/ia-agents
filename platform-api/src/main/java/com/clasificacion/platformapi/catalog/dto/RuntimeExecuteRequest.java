package com.clasificacion.platformapi.catalog.dto;

import jakarta.validation.constraints.NotBlank;
import java.util.Map;

public record RuntimeExecuteRequest(
    @NotBlank String org_id,
    @NotBlank String company_id,
    Map<String, Object> input
) {
}
