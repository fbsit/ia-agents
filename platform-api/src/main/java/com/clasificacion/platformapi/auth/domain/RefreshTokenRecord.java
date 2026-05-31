package com.clasificacion.platformapi.auth.domain;

import java.time.Instant;

public record RefreshTokenRecord(String tokenId, String userId, Instant expiresAt, boolean revoked) {
    public RefreshTokenRecord revoke() {
        return new RefreshTokenRecord(tokenId, userId, expiresAt, true);
    }
}
