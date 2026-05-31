package com.clasificacion.platformapi.auth.dto;

import jakarta.validation.constraints.NotBlank;

public record RefreshRequest(@NotBlank String refresh_token) {
}
