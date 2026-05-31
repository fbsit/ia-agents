package com.clasificacion.platformapi.auth.repository;

import com.clasificacion.platformapi.auth.domain.UserAccount;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcUserRepository {
    private final JdbcTemplate jdbcTemplate;

    public JdbcUserRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public Optional<UserAccount> findByEmail(String normalizedEmail) {
        List<UserAccount> items = jdbcTemplate.query(
            "SELECT user_id, email, password_hash FROM users WHERE email = ?",
            (_rs, _row) -> new UserAccount(
                _rs.getString("user_id"),
                _rs.getString("email"),
                _rs.getString("password_hash")
            ),
            normalizedEmail
        );
        return items.stream().findFirst();
    }

    public Optional<UserAccount> findById(String userId) {
        List<UserAccount> items = jdbcTemplate.query(
            "SELECT user_id, email, password_hash FROM users WHERE user_id = ?",
            (_rs, _row) -> new UserAccount(
                _rs.getString("user_id"),
                _rs.getString("email"),
                _rs.getString("password_hash")
            ),
            userId
        );
        return items.stream().findFirst();
    }

    public UserAccount create(String normalizedEmail, String passwordHash) {
        String userId = UUID.randomUUID().toString();
        try {
            jdbcTemplate.update(
                "INSERT INTO users (user_id, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                userId,
                normalizedEmail,
                passwordHash,
                Instant.now().getEpochSecond()
            );
            return new UserAccount(userId, normalizedEmail, passwordHash);
        } catch (DuplicateKeyException exc) {
            throw new IllegalStateException("El email ya esta registrado");
        }
    }
}
