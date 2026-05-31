package com.clasificacion.platformapi.auth.repository;

import com.clasificacion.platformapi.auth.domain.RefreshTokenRecord;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcRefreshTokenRepository {
    private final JdbcTemplate jdbcTemplate;

    public JdbcRefreshTokenRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public void save(RefreshTokenRecord token) {
        jdbcTemplate.update(
            """
            INSERT INTO refresh_tokens (token_id, user_id, expires_at, revoked, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(token_id) DO UPDATE SET
              user_id = excluded.user_id,
              expires_at = excluded.expires_at,
              revoked = excluded.revoked
            """,
            token.tokenId(),
            token.userId(),
            token.expiresAt().getEpochSecond(),
            token.revoked(),
            Instant.now().getEpochSecond()
        );
    }

    public Optional<RefreshTokenRecord> find(String tokenId) {
        long nowEpoch = Instant.now().getEpochSecond();
        List<RefreshTokenRecord> items = jdbcTemplate.query(
            """
            SELECT token_id, user_id, expires_at, revoked
            FROM refresh_tokens
            WHERE token_id = ? AND expires_at >= ?
            """,
            (rs, rowNum) -> new RefreshTokenRecord(
                rs.getString("token_id"),
                rs.getString("user_id"),
                Instant.ofEpochSecond(rs.getLong("expires_at")),
                rs.getBoolean("revoked")
            ),
            tokenId,
            nowEpoch
        );
        return items.stream().findFirst();
    }

    public void revoke(String tokenId) {
        jdbcTemplate.update(
            "UPDATE refresh_tokens SET revoked = TRUE WHERE token_id = ?",
            tokenId
        );
    }
}
