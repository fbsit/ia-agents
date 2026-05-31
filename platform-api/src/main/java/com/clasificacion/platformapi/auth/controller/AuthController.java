package com.clasificacion.platformapi.auth.controller;

import com.clasificacion.platformapi.auth.dto.AuthTokensResponse;
import com.clasificacion.platformapi.auth.dto.LoginRequest;
import com.clasificacion.platformapi.auth.dto.LoginResponse;
import com.clasificacion.platformapi.auth.dto.LogoutRequest;
import com.clasificacion.platformapi.auth.dto.MeResponse;
import com.clasificacion.platformapi.auth.dto.MembershipResponse;
import com.clasificacion.platformapi.auth.dto.RefreshRequest;
import com.clasificacion.platformapi.auth.dto.RegisterRequest;
import com.clasificacion.platformapi.auth.dto.RegisterResponse;
import com.clasificacion.platformapi.auth.service.AuthService;
import jakarta.validation.Valid;
import java.util.Map;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping
public class AuthController {
    private final AuthService authService;

    public AuthController(AuthService authService) {
        this.authService = authService;
    }

    @PostMapping("/auth/register")
    public RegisterResponse register(@Valid @RequestBody RegisterRequest request) {
        var user = authService.register(request.email(), request.password());
        return new RegisterResponse(user.userId(), user.email());
    }

    @PostMapping("/auth/login")
    public LoginResponse login(@Valid @RequestBody LoginRequest request) {
        var session = authService.login(request.email(), request.password());
        var memberships = session.memberships().stream()
            .map(item -> new MembershipResponse(item.orgId(), item.role()))
            .toList();
        var tokens = new AuthTokensResponse(
            session.tokens().accessToken(),
            session.tokens().refreshToken(),
            session.tokens().tokenType()
        );
        return new LoginResponse(session.user().userId(), session.user().email(), memberships, tokens);
    }

    @PostMapping("/auth/refresh")
    public AuthTokensResponse refresh(@Valid @RequestBody RefreshRequest request) {
        var tokens = authService.refresh(request.refresh_token());
        return new AuthTokensResponse(tokens.accessToken(), tokens.refreshToken(), tokens.tokenType());
    }

    @PostMapping("/auth/logout")
    public Map<String, String> logout(@Valid @RequestBody LogoutRequest request) {
        authService.logout(request.refresh_token());
        return Map.of("status", "ok");
    }

    @GetMapping("/me")
    public MeResponse me(@RequestHeader(value = "Authorization", required = false) String authorization) {
        var profile = authService.me(authorization);
        var memberships = profile.memberships().stream()
            .map(item -> new MembershipResponse(item.orgId(), item.role()))
            .toList();
        return new MeResponse(profile.user().userId(), profile.user().email(), memberships);
    }
}
