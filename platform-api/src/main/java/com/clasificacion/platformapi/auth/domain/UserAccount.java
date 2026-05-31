package com.clasificacion.platformapi.auth.domain;

public record UserAccount(String userId, String email, String passwordHash) {
}
