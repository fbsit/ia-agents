package com.clasificacion.platformapi.auth.dto;

public record AuthTokensResponse(
    String access_token,
    String refresh_token,
    String token_type
) {
}
