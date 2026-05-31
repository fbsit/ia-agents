package com.clasificacion.platformapi.tenancy.repository;

import com.clasificacion.platformapi.tenancy.domain.Membership;
import java.time.Instant;
import java.util.List;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcMembershipRepository {
    private final JdbcTemplate jdbcTemplate;

    public JdbcMembershipRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public void add(String userId, String orgId, String role) {
        jdbcTemplate.update(
            """
            INSERT INTO memberships (user_id, org_id, role, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, org_id) DO UPDATE SET
              role = excluded.role
            """,
            userId,
            orgId,
            role,
            Instant.now().getEpochSecond()
        );
    }

    public List<Membership> listByUserId(String userId) {
        return jdbcTemplate.query(
            "SELECT user_id, org_id, role FROM memberships WHERE user_id = ? ORDER BY created_at ASC",
            (rs, rowNum) -> new Membership(
                rs.getString("user_id"),
                rs.getString("org_id"),
                rs.getString("role")
            ),
            userId
        );
    }
}
