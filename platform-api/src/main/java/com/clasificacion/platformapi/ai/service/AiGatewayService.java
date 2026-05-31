package com.clasificacion.platformapi.ai.service;

import com.clasificacion.platformapi.ai.client.AiEngineClient;
import com.clasificacion.platformapi.ai.contract.AiAgentChatRequest;
import com.clasificacion.platformapi.ai.contract.AiAgentChatResponse;
import com.clasificacion.platformapi.ai.contract.AiAgentCreateRequest;
import com.clasificacion.platformapi.ai.contract.AiAgentDocumentResponse;
import com.clasificacion.platformapi.ai.contract.AiAgentDocumentUploadRequest;
import com.clasificacion.platformapi.ai.contract.AiAgentFeedbackSummaryResponse;
import com.clasificacion.platformapi.ai.contract.AiAgentIndexResponse;
import com.clasificacion.platformapi.ai.contract.AiAgentIndexStatusResponse;
import com.clasificacion.platformapi.ai.contract.AiAgentResponse;
import com.clasificacion.platformapi.ai.contract.AiAgentSetupStatusResponse;
import com.clasificacion.platformapi.ai.contract.AiAgentUpdateRequest;
import com.clasificacion.platformapi.ai.contract.AiAgentWhatsAppConfigResponse;
import com.clasificacion.platformapi.ai.contract.AiAgentWhatsAppConfigUpdateRequest;
import com.clasificacion.platformapi.ai.contract.AiAgentWhatsAppValidationResponse;
import com.clasificacion.platformapi.ai.contract.AiAgentWidgetConfigResponse;
import com.clasificacion.platformapi.ai.contract.AiDeleteResponse;
import com.clasificacion.platformapi.ai.contract.AiDocumentDeleteResponse;
import com.clasificacion.platformapi.ai.contract.AiTenantLlmSettingsResponse;
import com.clasificacion.platformapi.ai.contract.AiTenantLlmSettingsUpdateRequest;
import com.clasificacion.platformapi.ai.dto.AgentChatRequest;
import com.clasificacion.platformapi.ai.dto.CreateAgentRequest;
import com.clasificacion.platformapi.ai.dto.UpdateTenantLlmSettingsRequest;
import com.clasificacion.platformapi.ai.dto.UpdateAgentWhatsAppConfigRequest;
import com.clasificacion.platformapi.ai.dto.UpdateAgentRequest;
import com.clasificacion.platformapi.auth.service.AuthService;
import com.clasificacion.platformapi.tenancy.service.TenancyService;
import java.io.IOException;
import java.util.List;
import java.util.UUID;
import java.util.Base64;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.stereotype.Service;

@Service
public class AiGatewayService {
    private final AuthService authService;
    private final TenancyService tenancyService;
    private final AiEngineClient aiEngineClient;
    private final String integrationServiceToken;

    public AiGatewayService(
        AuthService authService,
        TenancyService tenancyService,
        AiEngineClient aiEngineClient,
        @Value("${app.integration.service-token:}") String integrationServiceToken
    ) {
        this.authService = authService;
        this.tenancyService = tenancyService;
        this.aiEngineClient = aiEngineClient;
        this.integrationServiceToken = integrationServiceToken == null ? "" : integrationServiceToken.trim();
    }

    public AiAgentResponse createAgent(
        String authorization,
        String requestId,
        CreateAgentRequest request
    ) {
        AiRequestContext context = resolveContext(
            authorization,
            request.company_id(),
            request.org_id(),
            requestId
        );

        AiAgentCreateRequest payload = new AiAgentCreateRequest(
            request.name(),
            request.objective(),
            request.tone(),
            request.description(),
            request.rag_backend(),
            request.generation_provider(),
            request.use_openai_generation(),
            request.openai_model()
        );
        return aiEngineClient.createAgent(context, payload);
    }

    public AiAgentChatResponse chatAgent(
        String authorization,
        String requestId,
        String agentId,
        AgentChatRequest request
    ) {
        AiRequestContext context = resolveContext(
            authorization,
            request.company_id(),
            request.org_id(),
            requestId
        );

        Integer topK = request.top_k() != null ? request.top_k() : 4;

        AiAgentChatRequest payload = new AiAgentChatRequest(
            request.message(),
            topK,
            request.session_id(),
            request.use_openai_generation(),
            request.generation_provider(),
            request.generation_model()
        );
        return aiEngineClient.chatAgent(context, agentId, payload);
    }

    public List<AiAgentResponse> listAgents(
        String authorization,
        String requestId,
        String requestedCompanyId,
        String requestedOrgId
    ) {
        AiRequestContext context = resolveContext(
            authorization,
            requestedCompanyId,
            requestedOrgId,
            requestId
        );
        return aiEngineClient.listAgents(context);
    }

    public AiAgentResponse updateAgent(
        String authorization,
        String requestId,
        String agentId,
        UpdateAgentRequest request
    ) {
        AiRequestContext context = resolveContext(
            authorization,
            request.company_id(),
            request.org_id(),
            requestId
        );

        AiAgentUpdateRequest payload = new AiAgentUpdateRequest(
            request.name(),
            request.objective(),
            request.tone(),
            request.description(),
            request.rag_backend(),
            request.generation_provider(),
            request.use_openai_generation(),
            request.openai_model()
        );
        return aiEngineClient.updateAgent(context, agentId, payload);
    }

    public AiDeleteResponse deleteAgent(
        String authorization,
        String requestId,
        String agentId,
        String requestedCompanyId,
        String requestedOrgId
    ) {
        AiRequestContext context = resolveContext(
            authorization,
            requestedCompanyId,
            requestedOrgId,
            requestId
        );
        return aiEngineClient.deleteAgent(context, agentId);
    }

    public List<AiAgentDocumentResponse> listAgentDocuments(
        String authorization,
        String requestId,
        String agentId,
        String requestedCompanyId,
        String requestedOrgId
    ) {
        AiRequestContext context = resolveContext(
            authorization,
            requestedCompanyId,
            requestedOrgId,
            requestId
        );
        return aiEngineClient.listAgentDocuments(context, agentId);
    }

    public AiAgentIndexResponse rebuildAgentIndex(
        String authorization,
        String requestId,
        String agentId,
        String requestedCompanyId,
        String requestedOrgId
    ) {
        AiRequestContext context = resolveContext(
            authorization,
            requestedCompanyId,
            requestedOrgId,
            requestId
        );
        return aiEngineClient.rebuildAgentIndex(context, agentId);
    }

    public AiAgentIndexStatusResponse getAgentIndexStatus(
        String authorization,
        String requestId,
        String agentId,
        String requestedCompanyId,
        String requestedOrgId
    ) {
        AiRequestContext context = resolveContext(
            authorization,
            requestedCompanyId,
            requestedOrgId,
            requestId
        );
        return aiEngineClient.getAgentIndexStatus(context, agentId);
    }

    public AiAgentDocumentResponse uploadAgentDocument(
        String authorization,
        String requestId,
        String agentId,
        String requestedCompanyId,
        String requestedOrgId,
        MultipartFile file,
        String operationalSection
    ) {
        AiRequestContext context = resolveContext(
            authorization,
            requestedCompanyId,
            requestedOrgId,
            requestId
        );

        String filename = file.getOriginalFilename();
        if (filename == null || filename.isBlank()) {
            throw new IllegalArgumentException("filename invalido");
        }

        byte[] content;
        try {
            content = file.getBytes();
        } catch (IOException exc) {
            throw new IllegalStateException("No se pudo leer archivo", exc);
        }
        String encoded = Base64.getEncoder().encodeToString(content);

        AiAgentDocumentUploadRequest payload = new AiAgentDocumentUploadRequest(
            filename,
            encoded,
            operationalSection
        );
        return aiEngineClient.uploadAgentDocument(context, agentId, payload);
    }

    public AiDocumentDeleteResponse deleteAgentDocument(
        String authorization,
        String requestId,
        String agentId,
        String documentId,
        String requestedCompanyId,
        String requestedOrgId
    ) {
        AiRequestContext context = resolveContext(
            authorization,
            requestedCompanyId,
            requestedOrgId,
            requestId
        );
        return aiEngineClient.deleteAgentDocument(context, agentId, documentId);
    }

    public AiAgentSetupStatusResponse getAgentSetupStatus(
        String authorization,
        String requestId,
        String agentId,
        String requestedCompanyId,
        String requestedOrgId
    ) {
        AiRequestContext context = resolveContext(
            authorization,
            requestedCompanyId,
            requestedOrgId,
            requestId
        );
        return aiEngineClient.getAgentSetupStatus(context, agentId);
    }

    public AiAgentWidgetConfigResponse getAgentWidgetConfig(
        String authorization,
        String requestId,
        String agentId,
        String requestedCompanyId,
        String requestedOrgId,
        String publicBaseUrl
    ) {
        AiRequestContext context = resolveContext(
            authorization,
            requestedCompanyId,
            requestedOrgId,
            requestId
        );
        return aiEngineClient.getAgentWidgetConfig(context, agentId, publicBaseUrl);
    }

    public AiAgentWhatsAppConfigResponse getAgentWhatsAppConfig(
        String authorization,
        String requestId,
        String agentId,
        String requestedCompanyId,
        String requestedOrgId,
        String publicBaseUrl
    ) {
        AiRequestContext context = resolveContext(
            authorization,
            requestedCompanyId,
            requestedOrgId,
            requestId
        );
        return aiEngineClient.getAgentWhatsAppConfig(context, agentId, publicBaseUrl);
    }

    public AiAgentWhatsAppConfigResponse updateAgentWhatsAppConfig(
        String authorization,
        String requestId,
        String agentId,
        UpdateAgentWhatsAppConfigRequest request,
        String publicBaseUrl
    ) {
        AiRequestContext context = resolveContext(
            authorization,
            request.company_id(),
            request.org_id(),
            requestId
        );

        AiAgentWhatsAppConfigUpdateRequest payload = new AiAgentWhatsAppConfigUpdateRequest(
            request.phone_number_id(),
            request.business_account_id(),
            request.verify_token()
        );
        return aiEngineClient.updateAgentWhatsAppConfig(context, agentId, payload, publicBaseUrl);
    }

    public AiAgentWhatsAppValidationResponse validateAgentWhatsAppConfig(
        String authorization,
        String requestId,
        String agentId,
        String requestedCompanyId,
        String requestedOrgId,
        String publicBaseUrl
    ) {
        AiRequestContext context = resolveContext(
            authorization,
            requestedCompanyId,
            requestedOrgId,
            requestId
        );
        return aiEngineClient.validateAgentWhatsAppConfig(context, agentId, publicBaseUrl);
    }

    public AiAgentFeedbackSummaryResponse getAgentFeedbackSummary(
        String authorization,
        String requestId,
        String agentId,
        String requestedCompanyId,
        String requestedOrgId,
        int days
    ) {
        AiRequestContext context = resolveContext(
            authorization,
            requestedCompanyId,
            requestedOrgId,
            requestId
        );
        return aiEngineClient.getAgentFeedbackSummary(context, agentId, days);
    }

    public AiTenantLlmSettingsResponse getTenantLlmSettings(
        String authorization,
        String requestId,
        String requestedCompanyId,
        String requestedOrgId
    ) {
        AiRequestContext context = resolveContext(
            authorization,
            requestedCompanyId,
            requestedOrgId,
            requestId
        );
        return aiEngineClient.getTenantLlmSettings(context);
    }

    public AiTenantLlmSettingsResponse updateTenantLlmSettings(
        String authorization,
        String requestId,
        UpdateTenantLlmSettingsRequest request
    ) {
        String requestedOrgId = request.org_id();
        if (requestedOrgId == null || requestedOrgId.isBlank()) {
            requestedOrgId = request.company_id();
        }

        AiRequestContext context = resolveContext(
            authorization,
            request.company_id(),
            requestedOrgId,
            requestId
        );
        AiTenantLlmSettingsUpdateRequest payload = new AiTenantLlmSettingsUpdateRequest(
            context.companyId(),
            request.generation_provider(),
            request.openai_model(),
            request.anthropic_model(),
            request.openai_api_key(),
            request.anthropic_api_key(),
            request.clear_openai_api_key(),
            request.clear_anthropic_api_key()
        );
        return aiEngineClient.updateTenantLlmSettings(context, payload);
    }

    private AiRequestContext resolveContext(
        String authorization,
        String requestedCompanyId,
        String requestedOrgId,
        String requestId
    ) {
        if (isIntegrationServiceAuth(authorization)) {
            String companyId = requestedCompanyId != null ? requestedCompanyId.trim() : "";
            String orgId = requestedOrgId != null ? requestedOrgId.trim() : "";
            if (companyId.isBlank() || orgId.isBlank()) {
                throw new IllegalArgumentException(
                    "company_id y org_id son requeridos para token de integracion"
                );
            }
            String effectiveRequestId = requestId == null || requestId.isBlank()
                ? UUID.randomUUID().toString()
                : requestId;
            return new AiRequestContext(
                companyId,
                orgId,
                "service:clubhx",
                effectiveRequestId
            );
        }

        var profile = authService.me(authorization);
        var organizations = tenancyService.listOrganizations(authorization);
        if (organizations.isEmpty()) {
            throw new IllegalArgumentException("El usuario no tiene organizaciones activas");
        }

        var selected = selectOrganization(organizations, requestedCompanyId, requestedOrgId);
        String effectiveRequestId = requestId == null || requestId.isBlank()
            ? UUID.randomUUID().toString()
            : requestId;

        return new AiRequestContext(
            selected.companyId(),
            selected.orgId(),
            profile.user().userId(),
            effectiveRequestId
        );
    }

    private boolean isIntegrationServiceAuth(String authorization) {
        if (integrationServiceToken.isBlank()) return false;
        if (authorization == null || authorization.isBlank()) return false;
        if (!authorization.startsWith("Bearer ")) return false;
        String token = authorization.substring("Bearer ".length()).trim();
        return integrationServiceToken.equals(token);
    }

    private TenancyService.OrganizationMembershipView selectOrganization(
        List<TenancyService.OrganizationMembershipView> organizations,
        String requestedCompanyId,
        String requestedOrgId
    ) {
        if (requestedOrgId != null && !requestedOrgId.isBlank()) {
            return organizations.stream()
                .filter(item -> requestedOrgId.equals(item.orgId()))
                .findFirst()
                .orElseThrow(() -> new IllegalArgumentException("org_id invalido o sin acceso"));
        }

        if (requestedCompanyId != null && !requestedCompanyId.isBlank()) {
            return organizations.stream()
                .filter(item -> requestedCompanyId.equals(item.companyId()))
                .findFirst()
                .orElseThrow(() -> new IllegalArgumentException("company_id invalido o sin acceso"));
        }

        if (organizations.size() == 1) {
            return organizations.get(0);
        }
        throw new IllegalArgumentException("Debes indicar org_id o company_id cuando tienes multiples organizaciones");
    }
}
