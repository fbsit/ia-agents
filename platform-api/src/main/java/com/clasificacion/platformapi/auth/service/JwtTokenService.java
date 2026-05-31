package com.clasificacion.platformapi.auth.service;

import com.clasificacion.platformapi.auth.config.AuthProperties;
import com.clasificacion.platformapi.auth.domain.TokenPair;
import com.clasificacion.platformapi.auth.exception.InvalidTokenException;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.Jws;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.io.Decoders;
import io.jsonwebtoken.security.Keys;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.Date;
import java.util.UUID;
import javax.crypto.SecretKey;
import org.springframework.stereotype.Service;

@Service
public class JwtTokenService {
    private final AuthProperties properties;
    private final SecretKey signingKey;

    public JwtTokenService(AuthProperties properties) {
        this.properties = properties;
        this.signingKey = buildKey(properties.jwt().secret());
    }

    public TokenPair issue(String userId, String email) {
        Instant now = Instant.now();
        Instant accessExpiration = now.plus(properties.accessTokenMinutes(), ChronoUnit.MINUTES);
        Instant refreshExpiration = now.plus(properties.refreshTokenDays(), ChronoUnit.DAYS);
        String refreshTokenId = UUID.randomUUID().toString();

        String accessToken = Jwts.builder()
            .subject(userId)
            .claim("email", email)
            .claim("token_type", "access")
            .issuedAt(Date.from(now))
            .expiration(Date.from(accessExpiration))
            .signWith(signingKey)
            .compact();

        String refreshToken = Jwts.builder()
            .subject(userId)
            .id(refreshTokenId)
            .claim("email", email)
            .claim("token_type", "refresh")
            .issuedAt(Date.from(now))
            .expiration(Date.from(refreshExpiration))
            .signWith(signingKey)
            .compact();

        return new TokenPair(accessToken, refreshToken, "bearer");
    }

    public AccessClaims parseAccessToken(String token) {
        Claims claims = parse(token, "access").getPayload();
        return new AccessClaims(claims.getSubject(), claims.get("email", String.class));
    }

    public RefreshClaims parseRefreshToken(String token) {
        Claims claims = parse(token, "refresh").getPayload();
        String tokenId = claims.getId();
        if (tokenId == null || tokenId.isBlank()) {
            throw new InvalidTokenException("Refresh token invalido");
        }
        return new RefreshClaims(claims.getSubject(), claims.get("email", String.class), tokenId, claims.getExpiration().toInstant());
    }

    private Jws<Claims> parse(String token, String expectedType) {
        try {
            Jws<Claims> parsed = Jwts.parser().verifyWith(signingKey).build().parseSignedClaims(token);
            String tokenType = parsed.getPayload().get("token_type", String.class);
            if (!expectedType.equals(tokenType)) {
                throw new InvalidTokenException("Tipo de token invalido");
            }
            return parsed;
        } catch (InvalidTokenException exc) {
            throw exc;
        } catch (Exception exc) {
            throw new InvalidTokenException("Token invalido o expirado");
        }
    }

    private SecretKey buildKey(String secret) {
        try {
            byte[] decoded = Decoders.BASE64.decode(secret);
            return Keys.hmacShaKeyFor(decoded);
        } catch (Exception ignored) {
            byte[] raw = secret.getBytes(StandardCharsets.UTF_8);
            if (raw.length < 32) {
                throw new IllegalStateException("app.auth.jwt.secret debe tener al menos 32 caracteres");
            }
            return Keys.hmacShaKeyFor(raw);
        }
    }

    public record AccessClaims(String userId, String email) {
    }

    public record RefreshClaims(String userId, String email, String tokenId, Instant expiresAt) {
    }
}
