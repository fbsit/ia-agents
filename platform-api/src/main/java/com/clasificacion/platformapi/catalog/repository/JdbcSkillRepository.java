package com.clasificacion.platformapi.catalog.repository;

import com.clasificacion.platformapi.catalog.domain.Skill;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcSkillRepository {
    private final JdbcTemplate jdbcTemplate;

    public JdbcSkillRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public Skill create(
        String orgId,
        String companyId,
        String name,
        String description,
        String definitionJson,
        String status
    ) {
        String skillId = UUID.randomUUID().toString();
        long now = Instant.now().getEpochSecond();
        jdbcTemplate.update(
            """
            INSERT INTO skills (skill_id, org_id, company_id, name, description, definition_json, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            skillId,
            orgId,
            companyId,
            name,
            description,
            definitionJson,
            status,
            now,
            now
        );
        return findByIdScoped(skillId, orgId, companyId).orElseThrow();
    }

    public List<Skill> listByTenant(String orgId, String companyId) {
        return jdbcTemplate.query(
            """
            SELECT s.skill_id, s.org_id, s.company_id, s.name, s.description, s.definition_json, s.status,
                   COALESCE((SELECT MAX(version) FROM skill_versions sv WHERE sv.skill_id = s.skill_id), 0) AS published_version
            FROM skills s
            WHERE org_id = ? AND company_id = ?
            ORDER BY s.updated_at DESC
            """,
            (rs, rowNum) -> new Skill(
                rs.getString("skill_id"),
                rs.getString("org_id"),
                rs.getString("company_id"),
                rs.getString("name"),
                rs.getString("description"),
                rs.getString("definition_json"),
                rs.getString("status"),
                toNullableVersion(rs.getInt("published_version"))
            ),
            orgId,
            companyId
        );
    }

    public Optional<Skill> updateScoped(
        String skillId,
        String orgId,
        String companyId,
        String name,
        String description,
        String definitionJson,
        String status
    ) {
        jdbcTemplate.update(
            """
            UPDATE skills
            SET name = COALESCE(?, name),
                description = COALESCE(?, description),
                definition_json = COALESCE(?, definition_json),
                status = COALESCE(?, status),
                updated_at = ?
            WHERE skill_id = ? AND org_id = ? AND company_id = ?
            """,
            name,
            description,
            definitionJson,
            status,
            Instant.now().getEpochSecond(),
            skillId,
            orgId,
            companyId
        );
        return findScoped(skillId, orgId, companyId);
    }

    public Optional<Skill> findScoped(String skillId, String orgId, String companyId) {
        List<Skill> items = jdbcTemplate.query(
            """
            SELECT s.skill_id, s.org_id, s.company_id, s.name, s.description, s.definition_json, s.status,
                   COALESCE((SELECT MAX(version) FROM skill_versions sv WHERE sv.skill_id = s.skill_id), 0) AS published_version
            FROM skills s
            WHERE skill_id = ? AND org_id = ? AND company_id = ?
            """,
            (rs, rowNum) -> new Skill(
                rs.getString("skill_id"),
                rs.getString("org_id"),
                rs.getString("company_id"),
                rs.getString("name"),
                rs.getString("description"),
                rs.getString("definition_json"),
                rs.getString("status"),
                toNullableVersion(rs.getInt("published_version"))
            ),
            skillId,
            orgId,
            companyId
        );
        return items.stream().findFirst();
    }

    private Integer toNullableVersion(int version) {
        return version <= 0 ? null : version;
    }

    public int publishScoped(String skillId, String orgId, String companyId, String createdByUserId) {
        Optional<Skill> current = findScoped(skillId, orgId, companyId);
        if (current.isEmpty()) {
            return -1;
        }

        Integer currentVersion = jdbcTemplate.queryForObject(
            "SELECT COALESCE(MAX(version), 0) FROM skill_versions WHERE skill_id = ?",
            Integer.class,
            skillId
        );
        int nextVersion = (currentVersion == null ? 0 : currentVersion) + 1;

        long now = Instant.now().getEpochSecond();
        jdbcTemplate.update(
            """
            INSERT INTO skill_versions (skill_id, version, definition_json, created_at, created_by_user_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            skillId,
            nextVersion,
            current.get().definitionJson(),
            now,
            createdByUserId
        );
        jdbcTemplate.update(
            """
            UPDATE skills
            SET status = ?, updated_at = ?
            WHERE skill_id = ? AND org_id = ? AND company_id = ?
            """,
            "published",
            now,
            skillId,
            orgId,
            companyId
        );
        return nextVersion;
    }

    public Integer latestVersion(String skillId) {
        return jdbcTemplate.queryForObject(
            "SELECT COALESCE(MAX(version), 0) FROM skill_versions WHERE skill_id = ?",
            Integer.class,
            skillId
        );
    }

    private Optional<Skill> findByIdScoped(String skillId, String orgId, String companyId) {
        return findScoped(skillId, orgId, companyId);
    }
}
