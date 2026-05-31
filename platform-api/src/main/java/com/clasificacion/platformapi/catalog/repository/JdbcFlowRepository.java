package com.clasificacion.platformapi.catalog.repository;

import com.clasificacion.platformapi.catalog.domain.Flow;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcFlowRepository {
    private final JdbcTemplate jdbcTemplate;

    public JdbcFlowRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public Flow create(
        String orgId,
        String companyId,
        String name,
        String description,
        String graphJson,
        String status
    ) {
        String flowId = UUID.randomUUID().toString();
        long now = Instant.now().getEpochSecond();
        jdbcTemplate.update(
            """
            INSERT INTO flows (flow_id, org_id, company_id, name, description, graph_json, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            flowId,
            orgId,
            companyId,
            name,
            description,
            graphJson,
            status,
            now,
            now
        );
        return findByIdScoped(flowId, orgId, companyId).orElseThrow();
    }

    public List<Flow> listByTenant(String orgId, String companyId) {
        return jdbcTemplate.query(
            """
            SELECT f.flow_id, f.org_id, f.company_id, f.name, f.description, f.graph_json, f.status,
                   COALESCE((SELECT MAX(version) FROM flow_versions fv WHERE fv.flow_id = f.flow_id), 0) AS published_version
            FROM flows f
            WHERE org_id = ? AND company_id = ?
            ORDER BY f.updated_at DESC
            """,
            (rs, rowNum) -> new Flow(
                rs.getString("flow_id"),
                rs.getString("org_id"),
                rs.getString("company_id"),
                rs.getString("name"),
                rs.getString("description"),
                rs.getString("graph_json"),
                rs.getString("status"),
                toNullableVersion(rs.getInt("published_version"))
            ),
            orgId,
            companyId
        );
    }

    public Optional<Flow> updateScoped(
        String flowId,
        String orgId,
        String companyId,
        String name,
        String description,
        String graphJson,
        String status
    ) {
        jdbcTemplate.update(
            """
            UPDATE flows
            SET name = COALESCE(?, name),
                description = COALESCE(?, description),
                graph_json = COALESCE(?, graph_json),
                status = COALESCE(?, status),
                updated_at = ?
            WHERE flow_id = ? AND org_id = ? AND company_id = ?
            """,
            name,
            description,
            graphJson,
            status,
            Instant.now().getEpochSecond(),
            flowId,
            orgId,
            companyId
        );
        return findScoped(flowId, orgId, companyId);
    }

    public Optional<Flow> findScoped(String flowId, String orgId, String companyId) {
        List<Flow> items = jdbcTemplate.query(
            """
            SELECT f.flow_id, f.org_id, f.company_id, f.name, f.description, f.graph_json, f.status,
                   COALESCE((SELECT MAX(version) FROM flow_versions fv WHERE fv.flow_id = f.flow_id), 0) AS published_version
            FROM flows f
            WHERE flow_id = ? AND org_id = ? AND company_id = ?
            """,
            (rs, rowNum) -> new Flow(
                rs.getString("flow_id"),
                rs.getString("org_id"),
                rs.getString("company_id"),
                rs.getString("name"),
                rs.getString("description"),
                rs.getString("graph_json"),
                rs.getString("status"),
                toNullableVersion(rs.getInt("published_version"))
            ),
            flowId,
            orgId,
            companyId
        );
        return items.stream().findFirst();
    }

    private Integer toNullableVersion(int version) {
        return version <= 0 ? null : version;
    }

    public int publishScoped(String flowId, String orgId, String companyId, String createdByUserId) {
        Optional<Flow> current = findScoped(flowId, orgId, companyId);
        if (current.isEmpty()) {
            return -1;
        }

        Integer currentVersion = jdbcTemplate.queryForObject(
            "SELECT COALESCE(MAX(version), 0) FROM flow_versions WHERE flow_id = ?",
            Integer.class,
            flowId
        );
        int nextVersion = (currentVersion == null ? 0 : currentVersion) + 1;

        long now = Instant.now().getEpochSecond();
        jdbcTemplate.update(
            """
            INSERT INTO flow_versions (flow_id, version, graph_json, created_at, created_by_user_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            flowId,
            nextVersion,
            current.get().graphJson(),
            now,
            createdByUserId
        );
        jdbcTemplate.update(
            """
            UPDATE flows
            SET status = ?, updated_at = ?
            WHERE flow_id = ? AND org_id = ? AND company_id = ?
            """,
            "published",
            now,
            flowId,
            orgId,
            companyId
        );
        return nextVersion;
    }

    public Integer latestVersion(String flowId) {
        return jdbcTemplate.queryForObject(
            "SELECT COALESCE(MAX(version), 0) FROM flow_versions WHERE flow_id = ?",
            Integer.class,
            flowId
        );
    }

    private Optional<Flow> findByIdScoped(String flowId, String orgId, String companyId) {
        return findScoped(flowId, orgId, companyId);
    }
}
