package com.clasificacion.platformapi.auth.domain;

public record TokenPair(String accessToken, String refreshToken, String tokenType) {
}
