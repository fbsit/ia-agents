package com.clasificacion.platformapi.auth.service;

import com.clasificacion.platformapi.auth.domain.RefreshTokenRecord;
import com.clasificacion.platformapi.auth.domain.TokenPair;
import com.clasificacion.platformapi.auth.domain.UserAccount;
import com.clasificacion.platformapi.auth.exception.EmailAlreadyExistsException;
import com.clasificacion.platformapi.auth.exception.InvalidCredentialsException;
import com.clasificacion.platformapi.auth.exception.InvalidTokenException;
import com.clasificacion.platformapi.auth.repository.JdbcRefreshTokenRepository;
import com.clasificacion.platformapi.auth.repository.JdbcUserRepository;
import com.clasificacion.platformapi.tenancy.service.TenancyService;
import java.util.List;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;

@Service
public class AuthService {
    private final JdbcUserRepository users;
    private final JdbcRefreshTokenRepository refreshTokens;
    private final JwtTokenService tokenService;
    private final TenancyService tenancyService;
    private final BCryptPasswordEncoder passwordEncoder = new BCryptPasswordEncoder();

    public AuthService(
        JdbcUserRepository users,
        JdbcRefreshTokenRepository refreshTokens,
        JwtTokenService tokenService,
        TenancyService tenancyService
    ) {
        this.users = users;
        this.refreshTokens = refreshTokens;
        this.tokenService = tokenService;
        this.tenancyService = tenancyService;
    }

    public UserAccount register(String email, String password) {
        String normalizedEmail = normalizeEmail(email);
        String passwordHash = passwordEncoder.encode(password);
        try {
            return users.create(normalizedEmail, passwordHash);
        } catch (IllegalStateException exc) {
            throw new EmailAlreadyExistsException();
        }
    }

    public AuthSession login(String email, String password) {
        String normalizedEmail = normalizeEmail(email);
        UserAccount user = users.findByEmail(normalizedEmail).orElseThrow(InvalidCredentialsException::new);
        if (!passwordEncoder.matches(password, user.passwordHash())) {
            throw new InvalidCredentialsException();
        }

        TokenPair tokens = tokenService.issue(user.userId(), user.email());
        JwtTokenService.RefreshClaims refreshClaims = tokenService.parseRefreshToken(tokens.refreshToken());
        refreshTokens.save(new RefreshTokenRecord(refreshClaims.tokenId(), user.userId(), refreshClaims.expiresAt(), false));

        List<Membership> memberships = tenancyService.listAuthMemberships(user.userId()).stream()
            .map(item -> new Membership(item.orgId(), item.role()))
            .toList();

        return new AuthSession(user, memberships, tokens);
    }

    public TokenPair refresh(String refreshToken) {
        JwtTokenService.RefreshClaims claims = tokenService.parseRefreshToken(refreshToken);
        RefreshTokenRecord record = refreshTokens.find(claims.tokenId())
            .orElseThrow(() -> new InvalidTokenException("Refresh token revocado o desconocido"));

        if (record.revoked()) {
            throw new InvalidTokenException("Refresh token revocado o desconocido");
        }

        UserAccount user = users.findById(record.userId())
            .orElseThrow(() -> new InvalidTokenException("Usuario invalido para refresh"));

        TokenPair newTokens = tokenService.issue(user.userId(), user.email());
        JwtTokenService.RefreshClaims newRefreshClaims = tokenService.parseRefreshToken(newTokens.refreshToken());

        refreshTokens.revoke(claims.tokenId());
        refreshTokens.save(new RefreshTokenRecord(newRefreshClaims.tokenId(), user.userId(), newRefreshClaims.expiresAt(), false));

        return newTokens;
    }

    public void logout(String refreshToken) {
        JwtTokenService.RefreshClaims claims = tokenService.parseRefreshToken(refreshToken);
        refreshTokens.revoke(claims.tokenId());
    }

    public UserProfile me(String bearerToken) {
        String token = extractBearerToken(bearerToken);
        JwtTokenService.AccessClaims claims = tokenService.parseAccessToken(token);
        UserAccount user = users.findById(claims.userId())
            .orElseThrow(() -> new InvalidCredentialsException("Usuario no encontrado"));
        List<Membership> memberships = tenancyService.listAuthMemberships(user.userId()).stream()
            .map(item -> new Membership(item.orgId(), item.role()))
            .toList();
        return new UserProfile(user, memberships);
    }

    private String extractBearerToken(String authorizationHeader) {
        if (authorizationHeader == null || !authorizationHeader.startsWith("Bearer ")) {
            throw new InvalidCredentialsException("Authorization header faltante o invalido");
        }
        return authorizationHeader.substring("Bearer ".length()).trim();
    }

    private String normalizeEmail(String email) {
        return email.trim().toLowerCase();
    }

    public record Membership(String orgId, String role) {
    }

    public record UserProfile(UserAccount user, List<Membership> memberships) {
    }

    public record AuthSession(UserAccount user, List<Membership> memberships, TokenPair tokens) {
    }
}
