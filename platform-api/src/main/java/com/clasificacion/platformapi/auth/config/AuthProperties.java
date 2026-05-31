package com.clasificacion.platformapi.auth.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "app.auth")
public record AuthProperties(
    Jwt jwt,
    long accessTokenMinutes,
    long refreshTokenDays
) {
    public record Jwt(String secret) {
    }
}
