package com.clasificacion.platformapi.auth.dto;

import jakarta.validation.constraints.NotBlank;

public record LogoutRequest(@NotBlank String refresh_token) {
}
