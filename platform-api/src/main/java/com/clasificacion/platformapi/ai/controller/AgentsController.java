package com.clasificacion.platformapi.ai.controller;

import com.clasificacion.platformapi.ai.dto.AgentChatRequest;
import com.clasificacion.platformapi.ai.dto.AgentChatResponse;
import com.clasificacion.platformapi.ai.dto.AgentDocumentResponse;
import com.clasificacion.platformapi.ai.dto.AgentFeedbackSummaryResponse;
import com.clasificacion.platformapi.ai.dto.AgentIndexResponse;
import com.clasificacion.platformapi.ai.dto.AgentIndexStatusResponse;
import com.clasificacion.platformapi.ai.dto.AgentResponse;
import com.clasificacion.platformapi.ai.dto.AgentSetupStatusResponse;
import com.clasificacion.platformapi.ai.dto.AgentSetupStepResponse;
import com.clasificacion.platformapi.ai.dto.AgentWhatsAppConfigResponse;
import com.clasificacion.platformapi.ai.dto.AgentWhatsAppValidationResponse;
import com.clasificacion.platformapi.ai.dto.AgentWidgetConfigResponse;
import com.clasificacion.platformapi.ai.dto.CreateAgentRequest;
import com.clasificacion.platformapi.ai.dto.DeleteAgentResponse;
import com.clasificacion.platformapi.ai.dto.DocumentDeleteResponse;
import com.clasificacion.platformapi.ai.dto.TenantLlmSettingsResponse;
import com.clasificacion.platformapi.ai.dto.UpdateTenantLlmSettingsRequest;
import com.clasificacion.platformapi.ai.dto.UpdateAgentWhatsAppConfigRequest;
import com.clasificacion.platformapi.ai.dto.UpdateAgentRequest;
import com.clasificacion.platformapi.ai.service.AiGatewayService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import java.net.URI;
import java.util.List;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.multipart.MultipartFile;

@RestController
@RequestMapping
public class AgentsController {
    private final AiGatewayService aiGatewayService;

    public AgentsController(AiGatewayService aiGatewayService) {
        this.aiGatewayService = aiGatewayService;
    }

    @GetMapping("/settings/llm")
    public TenantLlmSettingsResponse getTenantLlmSettings(
        @RequestHeader(value = "Authorization", required = false) String authorization,
        @RequestHeader(value = "X-Request-Id", required = false) String requestId,
        @RequestParam(value = "company_id", required = false) String companyId,
        @RequestParam(value = "org_id", required = false) String orgId
    ) {
        var response = aiGatewayService.getTenantLlmSettings(authorization, requestId, companyId, orgId);
        return new TenantLlmSettingsResponse(
            response.company_id(),
            response.generation_provider(),
            response.openai_model(),
            response.anthropic_model(),
            response.has_openai_api_key(),
            response.has_anthropic_api_key(),
            response.openai_api_key_masked(),
            response.anthropic_api_key_masked(),
            response.openai_key_source(),
            response.anthropic_key_source(),
            response.updated_at()
        );
    }

    @PutMapping("/settings/llm")
    public TenantLlmSettingsResponse updateTenantLlmSettings(
        @RequestBody UpdateTenantLlmSettingsRequest request,
        @RequestHeader(value = "Authorization", required = false) String authorization,
        @RequestHeader(value = "X-Request-Id", required = false) String requestId
    ) {
        var response = aiGatewayService.updateTenantLlmSettings(authorization, requestId, request);
        return new TenantLlmSettingsResponse(
            response.company_id(),
            response.generation_provider(),
            response.openai_model(),
            response.anthropic_model(),
            response.has_openai_api_key(),
            response.has_anthropic_api_key(),
            response.openai_api_key_masked(),
            response.anthropic_api_key_masked(),
            response.openai_key_source(),
            response.anthropic_key_source(),
            response.updated_at()
        );
    }

    @PostMapping("/agents")
    public AgentResponse createAgent(
        @Valid @RequestBody CreateAgentRequest request,
        @RequestHeader(value = "Authorization", required = false) String authorization,
        @RequestHeader(value = "X-Request-Id", required = false) String requestId
    ) {
        var created = aiGatewayService.createAgent(authorization, requestId, request);
        return new AgentResponse(
            created.agent_id(),
            created.org_id(),
            created.company_id(),
            created.name(),
            created.objective(),
            created.tone(),
            created.description(),
            created.rag_backend(),
            created.generation_provider(),
            created.use_openai_generation(),
            created.openai_model(),
            created.knowledge_dir(),
            created.index_path(),
            created.indexed_at(),
            created.documents_count()
        );
    }

    @PostMapping("/agents/{agentId}/chat")
    public AgentChatResponse chatAgent(
        @PathVariable String agentId,
        @Valid @RequestBody AgentChatRequest request,
        @RequestHeader(value = "Authorization", required = false) String authorization,
        @RequestHeader(value = "X-Request-Id", required = false) String requestId
    ) {
        var response = aiGatewayService.chatAgent(authorization, requestId, agentId, request);
        return new AgentChatResponse(
            response.agent_id(),
            response.company_id(),
            response.session_id(),
            response.answer(),
            response.sources(),
            response.intent_label(),
            response.route(),
            response.route_reason(),
            response.response_mode(),
            response.fallback_applied(),
            response.retrieval_min_score(),
            response.redirect_to()
        );
    }

    @GetMapping("/agents")
    public List<AgentResponse> listAgents(
        @RequestHeader(value = "Authorization", required = false) String authorization,
        @RequestHeader(value = "X-Request-Id", required = false) String requestId,
        @RequestParam(value = "company_id", required = false) String companyId,
        @RequestParam(value = "org_id", required = false) String orgId
    ) {
        return aiGatewayService.listAgents(authorization, requestId, companyId, orgId).stream()
            .map(item -> new AgentResponse(
                item.agent_id(),
                item.org_id(),
                item.company_id(),
                item.name(),
                item.objective(),
                item.tone(),
                item.description(),
                item.rag_backend(),
                item.generation_provider(),
                item.use_openai_generation(),
                item.openai_model(),
                item.knowledge_dir(),
                item.index_path(),
                item.indexed_at(),
                item.documents_count()
            ))
            .toList();
    }

    @PatchMapping("/agents/{agentId}")
    public AgentResponse updateAgent(
        @PathVariable String agentId,
        @RequestBody UpdateAgentRequest request,
        @RequestHeader(value = "Authorization", required = false) String authorization,
        @RequestHeader(value = "X-Request-Id", required = false) String requestId
    ) {
        var updated = aiGatewayService.updateAgent(authorization, requestId, agentId, request);
        return new AgentResponse(
            updated.agent_id(),
            updated.org_id(),
            updated.company_id(),
            updated.name(),
            updated.objective(),
            updated.tone(),
            updated.description(),
            updated.rag_backend(),
            updated.generation_provider(),
            updated.use_openai_generation(),
            updated.openai_model(),
            updated.knowledge_dir(),
            updated.index_path(),
            updated.indexed_at(),
            updated.documents_count()
        );
    }

    @DeleteMapping("/agents/{agentId}")
    public DeleteAgentResponse deleteAgent(
        @PathVariable String agentId,
        @RequestHeader(value = "Authorization", required = false) String authorization,
        @RequestHeader(value = "X-Request-Id", required = false) String requestId,
        @RequestParam(value = "company_id", required = false) String companyId,
        @RequestParam(value = "org_id", required = false) String orgId
    ) {
        var deleted = aiGatewayService.deleteAgent(authorization, requestId, agentId, companyId, orgId);
        return new DeleteAgentResponse(deleted.status(), deleted.agent_id());
    }

    @GetMapping("/agents/{agentId}/documents")
    public List<AgentDocumentResponse> listAgentDocuments(
        @PathVariable String agentId,
        @RequestHeader(value = "Authorization", required = false) String authorization,
        @RequestHeader(value = "X-Request-Id", required = false) String requestId,
        @RequestParam(value = "company_id", required = false) String companyId,
        @RequestParam(value = "org_id", required = false) String orgId
    ) {
        return aiGatewayService.listAgentDocuments(authorization, requestId, agentId, companyId, orgId).stream()
            .map(item -> new AgentDocumentResponse(
                item.document_id(),
                item.agent_id(),
                item.filename(),
                item.size_bytes(),
                item.status(),
                item.indexed_at(),
                item.error_message(),
                item.created_at(),
                item.operational_section(),
                item.learning_summary(),
                item.summary_updated_at()
            ))
            .toList();
    }

    @PostMapping("/agents/{agentId}/index/rebuild")
    public AgentIndexResponse rebuildAgentIndex(
        @PathVariable String agentId,
        @RequestHeader(value = "Authorization", required = false) String authorization,
        @RequestHeader(value = "X-Request-Id", required = false) String requestId,
        @RequestParam(value = "company_id", required = false) String companyId,
        @RequestParam(value = "org_id", required = false) String orgId
    ) {
        var response = aiGatewayService.rebuildAgentIndex(authorization, requestId, agentId, companyId, orgId);
        return new AgentIndexResponse(
            response.agent_id(),
            response.backend(),
            response.total_documents(),
            response.total_chunks(),
            response.companies(),
            response.index_path()
        );
    }

    @GetMapping("/agents/{agentId}/index/status")
    public AgentIndexStatusResponse getAgentIndexStatus(
        @PathVariable String agentId,
        @RequestHeader(value = "Authorization", required = false) String authorization,
        @RequestHeader(value = "X-Request-Id", required = false) String requestId,
        @RequestParam(value = "company_id", required = false) String companyId,
        @RequestParam(value = "org_id", required = false) String orgId
    ) {
        var response = aiGatewayService.getAgentIndexStatus(authorization, requestId, agentId, companyId, orgId);
        return new AgentIndexStatusResponse(
            response.agent_id(),
            response.has_index(),
            response.indexed_at(),
            response.documents_total(),
            response.documents_indexed(),
            response.documents_failed(),
            response.documents_uploaded(),
            response.last_error()
        );
    }

    @PostMapping(value = "/agents/{agentId}/documents", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public AgentDocumentResponse uploadAgentDocument(
        @PathVariable String agentId,
        @RequestParam("file") MultipartFile file,
        @RequestParam(value = "operational_section", required = false) String operationalSection,
        @RequestHeader(value = "Authorization", required = false) String authorization,
        @RequestHeader(value = "X-Request-Id", required = false) String requestId,
        @RequestParam(value = "company_id", required = false) String companyId,
        @RequestParam(value = "org_id", required = false) String orgId
    ) {
        var uploaded = aiGatewayService.uploadAgentDocument(
            authorization,
            requestId,
            agentId,
            companyId,
            orgId,
            file,
            operationalSection
        );

        return new AgentDocumentResponse(
            uploaded.document_id(),
            uploaded.agent_id(),
            uploaded.filename(),
            uploaded.size_bytes(),
            uploaded.status(),
            uploaded.indexed_at(),
            uploaded.error_message(),
            uploaded.created_at(),
            uploaded.operational_section(),
            uploaded.learning_summary(),
            uploaded.summary_updated_at()
        );
    }

    @DeleteMapping("/agents/{agentId}/documents/{documentId}")
    public DocumentDeleteResponse deleteAgentDocument(
        @PathVariable String agentId,
        @PathVariable String documentId,
        @RequestHeader(value = "Authorization", required = false) String authorization,
        @RequestHeader(value = "X-Request-Id", required = false) String requestId,
        @RequestParam(value = "company_id", required = false) String companyId,
        @RequestParam(value = "org_id", required = false) String orgId
    ) {
        var deleted = aiGatewayService.deleteAgentDocument(
            authorization,
            requestId,
            agentId,
            documentId,
            companyId,
            orgId
        );
        return new DocumentDeleteResponse(deleted.status(), deleted.document_id());
    }

    @GetMapping("/agents/{agentId}/setup-status")
    public AgentSetupStatusResponse getAgentSetupStatus(
        @PathVariable String agentId,
        @RequestHeader(value = "Authorization", required = false) String authorization,
        @RequestHeader(value = "X-Request-Id", required = false) String requestId,
        @RequestParam(value = "company_id", required = false) String companyId,
        @RequestParam(value = "org_id", required = false) String orgId
    ) {
        var response = aiGatewayService.getAgentSetupStatus(
            authorization,
            requestId,
            agentId,
            companyId,
            orgId
        );
        return new AgentSetupStatusResponse(
            response.agent_id(),
            response.company_id(),
            response.agent_name(),
            response.rag_backend(),
            response.progress_percent(),
            response.ready_to_publish(),
            response.next_href(),
            response.documents_total(),
            response.documents_indexed(),
            response.test_messages(),
            response.steps().stream()
                .map(item -> new AgentSetupStepResponse(
                    item.id(),
                    item.label(),
                    item.description(),
                    item.ready(),
                    item.href()
                ))
                .toList()
        );
    }

    @GetMapping("/agents/{agentId}/widget-config")
    public AgentWidgetConfigResponse getAgentWidgetConfig(
        @PathVariable String agentId,
        @RequestHeader(value = "Authorization", required = false) String authorization,
        @RequestHeader(value = "X-Request-Id", required = false) String requestId,
        @RequestParam(value = "company_id", required = false) String companyId,
        @RequestParam(value = "org_id", required = false) String orgId,
        HttpServletRequest request
    ) {
        var response = aiGatewayService.getAgentWidgetConfig(
            authorization,
            requestId,
            agentId,
            companyId,
            orgId,
            resolvePublicBaseUrl(request)
        );
        return new AgentWidgetConfigResponse(
            response.agent_id(),
            response.widget_id(),
            response.endpoint_url(),
            response.widget_token(),
            response.allowed_origins(),
            response.rate_limit_window_seconds(),
            response.rate_limit_max_requests(),
            response.snippet_html()
        );
    }

    @GetMapping("/agents/{agentId}/channels/whatsapp/config")
    public AgentWhatsAppConfigResponse getAgentWhatsAppConfig(
        @PathVariable String agentId,
        @RequestHeader(value = "Authorization", required = false) String authorization,
        @RequestHeader(value = "X-Request-Id", required = false) String requestId,
        @RequestParam(value = "company_id", required = false) String companyId,
        @RequestParam(value = "org_id", required = false) String orgId,
        HttpServletRequest request
    ) {
        var response = aiGatewayService.getAgentWhatsAppConfig(
            authorization,
            requestId,
            agentId,
            companyId,
            orgId,
            resolvePublicBaseUrl(request)
        );
        return new AgentWhatsAppConfigResponse(
            response.agent_id(),
            response.company_id(),
            response.webhook_url(),
            response.phone_number_id(),
            response.business_account_id(),
            response.verify_token(),
            response.updated_at()
        );
    }

    @PutMapping("/agents/{agentId}/channels/whatsapp/config")
    public AgentWhatsAppConfigResponse updateAgentWhatsAppConfig(
        @PathVariable String agentId,
        @RequestBody UpdateAgentWhatsAppConfigRequest requestPayload,
        @RequestHeader(value = "Authorization", required = false) String authorization,
        @RequestHeader(value = "X-Request-Id", required = false) String requestId,
        HttpServletRequest request
    ) {
        var response = aiGatewayService.updateAgentWhatsAppConfig(
            authorization,
            requestId,
            agentId,
            requestPayload,
            resolvePublicBaseUrl(request)
        );
        return new AgentWhatsAppConfigResponse(
            response.agent_id(),
            response.company_id(),
            response.webhook_url(),
            response.phone_number_id(),
            response.business_account_id(),
            response.verify_token(),
            response.updated_at()
        );
    }

    @PostMapping("/agents/{agentId}/channels/whatsapp/validate")
    public AgentWhatsAppValidationResponse validateAgentWhatsAppConfig(
        @PathVariable String agentId,
        @RequestHeader(value = "Authorization", required = false) String authorization,
        @RequestHeader(value = "X-Request-Id", required = false) String requestId,
        @RequestParam(value = "company_id", required = false) String companyId,
        @RequestParam(value = "org_id", required = false) String orgId,
        HttpServletRequest request
    ) {
        var response = aiGatewayService.validateAgentWhatsAppConfig(
            authorization,
            requestId,
            agentId,
            companyId,
            orgId,
            resolvePublicBaseUrl(request)
        );
        return new AgentWhatsAppValidationResponse(
            response.agent_id(),
            response.company_id(),
            response.ready(),
            response.has_phone_number_id(),
            response.has_verify_token(),
            response.server_has_access_token(),
            response.company_map_ready(),
            response.webhook_url(),
            response.messages()
        );
    }

    @GetMapping("/agents/{agentId}/feedback/summary")
    public AgentFeedbackSummaryResponse getAgentFeedbackSummary(
        @PathVariable String agentId,
        @RequestHeader(value = "Authorization", required = false) String authorization,
        @RequestHeader(value = "X-Request-Id", required = false) String requestId,
        @RequestParam(value = "company_id", required = false) String companyId,
        @RequestParam(value = "org_id", required = false) String orgId,
        @RequestParam(value = "days", required = false, defaultValue = "30") int days
    ) {
        var response = aiGatewayService.getAgentFeedbackSummary(
            authorization,
            requestId,
            agentId,
            companyId,
            orgId,
            days
        );
        return new AgentFeedbackSummaryResponse(
            response.company_id(),
            response.agent_id(),
            response.feedback_total(),
            response.thumbs_up(),
            response.thumbs_down(),
            response.positive_rate(),
            response.with_comment(),
            response.with_expected_answer()
        );
    }

    private String resolvePublicBaseUrl(HttpServletRequest request) {
        String explicitPublicBase = request.getHeader("X-Public-Base-Url");
        if (explicitPublicBase != null && !explicitPublicBase.isBlank()) {
            return explicitPublicBase.strip();
        }

        String origin = request.getHeader("Origin");
        String originBase = toBaseUrl(origin);
        if (originBase != null) {
            return originBase;
        }

        String referer = request.getHeader("Referer");
        String refererBase = toBaseUrl(referer);
        if (refererBase != null) {
            return refererBase;
        }

        String scheme = request.getScheme();
        String host = request.getServerName();
        int port = request.getServerPort();
        boolean standardPort = ("http".equalsIgnoreCase(scheme) && port == 80)
            || ("https".equalsIgnoreCase(scheme) && port == 443);
        if (standardPort) {
            return scheme + "://" + host;
        }
        return scheme + "://" + host + ":" + port;
    }

    private String toBaseUrl(String rawUrl) {
        if (rawUrl == null || rawUrl.isBlank()) {
            return null;
        }
        try {
            URI uri = URI.create(rawUrl.trim());
            String scheme = uri.getScheme();
            String host = uri.getHost();
            int port = uri.getPort();
            if (scheme == null || host == null) {
                return null;
            }
            boolean standardPort = ("http".equalsIgnoreCase(scheme) && port == 80)
                || ("https".equalsIgnoreCase(scheme) && port == 443);
            if (port < 0 || standardPort) {
                return scheme + "://" + host;
            }
            return scheme + "://" + host + ":" + port;
        } catch (RuntimeException ignored) {
            return null;
        }
    }
}
