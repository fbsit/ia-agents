package com.clasificacion.platformapi.catalog.service;

import com.clasificacion.platformapi.auth.service.AuthService;
import com.clasificacion.platformapi.ai.client.AiEngineClient;
import com.clasificacion.platformapi.ai.contract.AiRuntimeExecuteRequest;
import com.clasificacion.platformapi.ai.contract.AiRuntimeExecuteResponse;
import com.clasificacion.platformapi.ai.service.AiRequestContext;
import com.clasificacion.platformapi.catalog.domain.Flow;
import com.clasificacion.platformapi.catalog.domain.Skill;
import com.clasificacion.platformapi.catalog.dto.CreateFlowRequest;
import com.clasificacion.platformapi.catalog.dto.CreateSkillRequest;
import com.clasificacion.platformapi.catalog.dto.RuntimeExecuteRequest;
import com.clasificacion.platformapi.catalog.dto.UpdateFlowRequest;
import com.clasificacion.platformapi.catalog.dto.UpdateSkillRequest;
import com.clasificacion.platformapi.catalog.exception.CatalogException;
import com.clasificacion.platformapi.catalog.repository.JdbcFlowRepository;
import com.clasificacion.platformapi.catalog.repository.JdbcSkillRepository;
import com.clasificacion.platformapi.tenancy.repository.JdbcOrganizationRepository;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import java.util.List;

@Service
public class CatalogService {
    private static final String STATUS_DRAFT = "draft";
    private static final String STATUS_PUBLISHED = "published";
    private static final String STATUS_ARCHIVED = "archived";

    private final AuthService authService;
    private final JdbcOrganizationRepository organizations;
    private final JdbcSkillRepository skills;
    private final JdbcFlowRepository flows;
    private final AiEngineClient aiEngineClient;

    public CatalogService(
        AuthService authService,
        JdbcOrganizationRepository organizations,
        JdbcSkillRepository skills,
        JdbcFlowRepository flows,
        AiEngineClient aiEngineClient
    ) {
        this.authService = authService;
        this.organizations = organizations;
        this.skills = skills;
        this.flows = flows;
        this.aiEngineClient = aiEngineClient;
    }

    public Skill createSkill(String authorization, CreateSkillRequest request) {
        TenantScope scope = resolveScope(authorization, request.org_id(), request.company_id());
        return skills.create(
            scope.orgId(),
            scope.companyId(),
            request.name().trim(),
            normalizeText(request.description()),
            normalizeJson(request.definition_json(), "{}"),
            normalizeStatus(request.status())
        );
    }

    public List<Skill> listSkills(String authorization, String orgId, String companyId) {
        TenantScope scope = resolveScope(authorization, orgId, companyId);
        return skills.listByTenant(scope.orgId(), scope.companyId());
    }

    public Skill updateSkill(String authorization, String skillId, UpdateSkillRequest request) {
        TenantScope scope = resolveScope(authorization, request.org_id(), request.company_id());
        return skills.updateScoped(
            skillId,
            scope.orgId(),
            scope.companyId(),
            normalizeOptionalText(request.name()),
            normalizeOptionalText(request.description()),
            normalizeOptionalJson(request.definition_json()),
            normalizeOptionalStatus(request.status())
        ).orElseThrow(() -> new CatalogException(HttpStatus.NOT_FOUND, "Skill no encontrada"));
    }

    public Flow createFlow(String authorization, CreateFlowRequest request) {
        TenantScope scope = resolveScope(authorization, request.org_id(), request.company_id());
        return flows.create(
            scope.orgId(),
            scope.companyId(),
            request.name().trim(),
            normalizeText(request.description()),
            normalizeJson(request.graph_json(), "{}"),
            normalizeStatus(request.status())
        );
    }

    public List<Flow> listFlows(String authorization, String orgId, String companyId) {
        TenantScope scope = resolveScope(authorization, orgId, companyId);
        return flows.listByTenant(scope.orgId(), scope.companyId());
    }

    public Flow updateFlow(String authorization, String flowId, UpdateFlowRequest request) {
        TenantScope scope = resolveScope(authorization, request.org_id(), request.company_id());
        return flows.updateScoped(
            flowId,
            scope.orgId(),
            scope.companyId(),
            normalizeOptionalText(request.name()),
            normalizeOptionalText(request.description()),
            normalizeOptionalJson(request.graph_json()),
            normalizeOptionalStatus(request.status())
        ).orElseThrow(() -> new CatalogException(HttpStatus.NOT_FOUND, "Flow no encontrado"));
    }

    public int publishSkill(String authorization, String skillId, String orgId, String companyId) {
        TenantScope scope = resolveScope(authorization, orgId, companyId);
        String userId = authService.me(authorization).user().userId();
        int version = skills.publishScoped(skillId, scope.orgId(), scope.companyId(), userId);
        if (version < 0) {
            throw new CatalogException(HttpStatus.NOT_FOUND, "Skill no encontrada");
        }
        return version;
    }

    public int publishFlow(String authorization, String flowId, String orgId, String companyId) {
        TenantScope scope = resolveScope(authorization, orgId, companyId);
        String userId = authService.me(authorization).user().userId();
        int version = flows.publishScoped(flowId, scope.orgId(), scope.companyId(), userId);
        if (version < 0) {
            throw new CatalogException(HttpStatus.NOT_FOUND, "Flow no encontrado");
        }
        return version;
    }

    public AiRuntimeExecuteResponse executePublishedSkill(
        String authorization,
        String skillId,
        RuntimeExecuteRequest request
    ) {
        TenantScope scope = resolveScope(authorization, request.org_id(), request.company_id());
        Skill skill = skills.findScoped(skillId, scope.orgId(), scope.companyId())
            .orElseThrow(() -> new CatalogException(HttpStatus.NOT_FOUND, "Skill no encontrada"));
        if (!STATUS_PUBLISHED.equals(skill.status())) {
            throw new CatalogException(HttpStatus.BAD_REQUEST, "La skill debe estar publicada antes de ejecutar");
        }

        Integer version = skills.latestVersion(skillId);
        if (version == null || version <= 0) {
            throw new CatalogException(HttpStatus.BAD_REQUEST, "No hay version publicada para la skill");
        }

        AiRequestContext context = resolveAiRequestContext(authorization, scope);
        return aiEngineClient.executePublishedSkill(
            context,
            skillId,
            new AiRuntimeExecuteRequest(version, request.input())
        );
    }

    public AiRuntimeExecuteResponse executePublishedFlow(
        String authorization,
        String flowId,
        RuntimeExecuteRequest request
    ) {
        TenantScope scope = resolveScope(authorization, request.org_id(), request.company_id());
        Flow flow = flows.findScoped(flowId, scope.orgId(), scope.companyId())
            .orElseThrow(() -> new CatalogException(HttpStatus.NOT_FOUND, "Flow no encontrado"));
        if (!STATUS_PUBLISHED.equals(flow.status())) {
            throw new CatalogException(HttpStatus.BAD_REQUEST, "El flow debe estar publicado antes de ejecutar");
        }

        Integer version = flows.latestVersion(flowId);
        if (version == null || version <= 0) {
            throw new CatalogException(HttpStatus.BAD_REQUEST, "No hay version publicada para el flow");
        }

        AiRequestContext context = resolveAiRequestContext(authorization, scope);
        return aiEngineClient.executePublishedFlow(
            context,
            flowId,
            new AiRuntimeExecuteRequest(version, request.input())
        );
    }

    private TenantScope resolveScope(String authorization, String orgId, String companyId) {
        var profile = authService.me(authorization);
        var organization = organizations.findById(orgId)
            .orElseThrow(() -> new CatalogException(HttpStatus.BAD_REQUEST, "org_id invalido"));

        if (!organization.companyId().equals(companyId)) {
            throw new CatalogException(HttpStatus.BAD_REQUEST, "company_id no coincide con org_id");
        }

        boolean hasMembership = profile.memberships().stream()
            .anyMatch(membership -> membership.orgId().equals(orgId));
        if (!hasMembership) {
            throw new CatalogException(HttpStatus.FORBIDDEN, "No tienes acceso a ese org_id");
        }

        return new TenantScope(orgId, companyId);
    }

    private AiRequestContext resolveAiRequestContext(String authorization, TenantScope scope) {
        var profile = authService.me(authorization);
        return new AiRequestContext(
            scope.companyId(),
            scope.orgId(),
            profile.user().userId(),
            java.util.UUID.randomUUID().toString()
        );
    }

    private String normalizeText(String value) {
        if (value == null) {
            return "";
        }
        return value.trim();
    }

    private String normalizeOptionalText(String value) {
        if (value == null) {
            return null;
        }
        return value.trim();
    }

    private String normalizeJson(String value, String fallback) {
        if (value == null || value.isBlank()) {
            return fallback;
        }
        return value;
    }

    private String normalizeOptionalJson(String value) {
        if (value == null) {
            return null;
        }
        if (value.isBlank()) {
            return "{}";
        }
        return value;
    }

    private String normalizeStatus(String status) {
        if (status == null || status.isBlank()) {
            return STATUS_DRAFT;
        }
        return assertStatus(status);
    }

    private String normalizeOptionalStatus(String status) {
        if (status == null) {
            return null;
        }
        if (status.isBlank()) {
            return STATUS_DRAFT;
        }
        return assertStatus(status);
    }

    private String assertStatus(String status) {
        String normalized = status.trim().toLowerCase();
        if (!normalized.equals(STATUS_DRAFT) && !normalized.equals(STATUS_PUBLISHED) && !normalized.equals(STATUS_ARCHIVED)) {
            throw new CatalogException(HttpStatus.BAD_REQUEST, "status invalido. Usa draft, published o archived");
        }
        return normalized;
    }

    private record TenantScope(String orgId, String companyId) {
    }
}
