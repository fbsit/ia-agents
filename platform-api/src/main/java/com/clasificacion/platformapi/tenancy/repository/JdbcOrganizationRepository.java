package com.clasificacion.platformapi.tenancy.repository;

import com.clasificacion.platformapi.tenancy.domain.Organization;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcOrganizationRepository {
    private final JdbcTemplate jdbcTemplate;

    public JdbcOrganizationRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public Organization create(String name, String companyId) {
        String orgId = UUID.randomUUID().toString();
        try {
            jdbcTemplate.update(
                "INSERT INTO organizations (org_id, company_id, name, created_at) VALUES (?, ?, ?, ?)",
                orgId,
                companyId,
                name,
                Instant.now().getEpochSecond()
            );
            return new Organization(orgId, companyId, name);
        } catch (DuplicateKeyException exc) {
            throw new IllegalStateException("company_id ya registrado");
        }
    }

    public Optional<Organization> findById(String orgId) {
        List<Organization> items = jdbcTemplate.query(
            "SELECT org_id, company_id, name FROM organizations WHERE org_id = ?",
            (rs, rowNum) -> new Organization(
                rs.getString("org_id"),
                rs.getString("company_id"),
                rs.getString("name")
            ),
            orgId
        );
        return items.stream().findFirst();
    }
}
