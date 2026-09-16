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
import com.clasificacion.platformapi.ai.dto.ConversationMessageResponse;
import com.clasificacion.platformapi.ai.dto.ConversationReplyRequest;
import com.clasificacion.platformapi.ai.dto.ConversationReplyResponse;
import com.clasificacion.platformapi.ai.dto.ConversationStatusResponse;
import com.clasificacion.platformapi.ai.dto.ConversationSummaryResponse;
import com.clasificacion.platformapi.ai.dto.CreateAgentRequest;
import com.clasificacion.platformapi.ai.dto.DeleteAgentResponse;
import com.clasificacion.platformapi.ai.dto.DocumentDeleteResponse;
import com.clasificacion.platformapi.ai.dto.TenantLlmSettingsResponse;
import com.clasificacion.platformapi.ai.dto.UpdateTenantLlmSettingsRequest;
import com.clasificacion.platformapi.ai.dto.UpdateAgentWhatsAppConfigRequest;
import com.clasificacion.platformapi.ai.dto.UpdateAgentRequest;
import com.clasificacion.platformapi.ai.dto.MediaTranscriptionResponse;
import com.clasificacion.platformapi.ai.service.AiGatewayService;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import java.util.List;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.ScheduledFuture;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
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
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

@RestController
@RequestMapping
public class AgentsController {
    private static final Logger log = LoggerFactory.getLogger(AgentsController.class);
    private static final long CONVERSATION_STREAM_POLL_MS = 2000;
    private static final long CONVERSATION_STREAM_TIMEOUT_MS = 5 * 60 * 1000;
    private final AiGatewayService aiGatewayService;
    private final ObjectMapper objectMapper;
    private final ScheduledExecutorService conversationStreamScheduler;

    public AgentsController(
        AiGatewayService aiGatewayService,
        ObjectMapper objectMapper,
        ScheduledExecutorService conversationStreamScheduler
    ) {
        this.aiGatewayService = aiGatewayService;
        this.objectMapper = objectMapper;
        this.conversationStreamScheduler = conversationStreamScheduler;
    }

    private static String resolveAuthorization(String authorization, String accessToken) {
        if (authorization != null && !authorization.isBlank()) {
            return authorization;
        }
        if (accessToken != null && !accessToken.isBlank()) {
            return "Bearer " + accessToken;
        }
        return authorization;
    }

    private String writeJsonQuietly(Object value) {
        try {
            return objectMapper.writeValueAsString(value);
        } catch (Exception exc) {
            log.warn("conversation_stream_serialize_error error={}", exc.getMessage());
            return "[]";
        }
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
            created.documents_count(),
            created.clubhx_tenant_id(),
            created.clubhx_shop_domain(),
            created.clubhx_storefront_url()
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
            response.redirect_to(),
            response.workflow_action(),
            response.cart_action(),
            response.cart_actions(),
            response.products()
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
                item.documents_count(),
                item.clubhx_tenant_id(),
                item.clubhx_shop_domain(),
                item.clubhx_storefront_url()
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
            updated.documents_count(),
            updated.clubhx_tenant_id(),
            updated.clubhx_shop_domain(),
            updated.clubhx_storefront_url()
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

    @PostMapping(value = "/media/transcriptions", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public MediaTranscriptionResponse transcribeMedia(
        @RequestParam("file") MultipartFile file,
        @RequestParam(value = "mime_type", required = false) String mimeType,
        @RequestParam(value = "language_hint", required = false) String languageHint,
        @RequestParam(value = "channel", required = false) String channel,
        @RequestParam(value = "source", required = false) String source,
        @RequestParam(value = "session_id", required = false) String sessionId,
        @RequestParam(value = "conversation_id", required = false) String conversationId,
        @RequestParam(value = "phone_number_id", required = false) String phoneNumberId,
        @RequestHeader(value = "Authorization", required = false) String authorization,
        @RequestHeader(value = "X-Request-Id", required = false) String requestId,
        @RequestParam(value = "company_id", required = false) String companyId,
        @RequestParam(value = "org_id", required = false) String orgId
    ) {
        log.info(
            "ai_transcribe_controller_start company_id={} org_id={} channel={} source={} has_file={} has_mime={} has_language_hint={} has_session={} has_conversation={} has_phone_number_id={}",
            companyId,
            orgId,
            channel,
            source,
            file != null,
            mimeType != null && !mimeType.isBlank(),
            languageHint != null && !languageHint.isBlank(),
            sessionId != null && !sessionId.isBlank(),
            conversationId != null && !conversationId.isBlank(),
            phoneNumberId != null && !phoneNumberId.isBlank()
        );
        var response = aiGatewayService.transcribeMedia(
            authorization,
            requestId,
            companyId,
            orgId,
            file,
            mimeType,
            languageHint,
            channel,
            source,
            sessionId,
            conversationId,
            phoneNumberId
        );
        log.info(
            "ai_transcribe_controller_ok company_id={} org_id={} text_len={} provider={}",
            companyId,
            orgId,
            response.text() == null ? 0 : response.text().length(),
            response.provider()
        );
        return new MediaTranscriptionResponse(
            response.text(),
            response.language(),
            response.confidence(),
            response.duration_ms(),
            response.provider()
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
            response.messages_stream_url(),
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

    @GetMapping("/agents/{agentId}/conversations")
    public java.util.List<ConversationSummaryResponse> listConversations(
        @PathVariable String agentId,
        @RequestHeader(value = "Authorization", required = false) String authorization,
        @RequestHeader(value = "X-Request-Id", required = false) String requestId,
        @RequestParam(value = "company_id", required = false) String companyId,
        @RequestParam(value = "org_id", required = false) String orgId,
        @RequestParam(value = "status", required = false) String status,
        @RequestParam(value = "limit", required = false, defaultValue = "50") int limit
    ) {
        return aiGatewayService
            .listConversations(authorization, requestId, agentId, companyId, orgId, status, limit)
            .stream()
            .map(row -> new ConversationSummaryResponse(
                row.session_id(),
                row.channel(),
                row.status(),
                row.message_count(),
                row.started_at(),
                row.updated_at(),
                row.visitor_id(),
                row.external_user_id(),
                row.authenticated_user_id(),
                row.last_message_preview()
            ))
            .toList();
    }

    @GetMapping("/agents/{agentId}/conversations/{sessionId}/messages")
    public java.util.List<ConversationMessageResponse> getConversationMessages(
        @PathVariable String agentId,
        @PathVariable String sessionId,
        @RequestHeader(value = "Authorization", required = false) String authorization,
        @RequestHeader(value = "X-Request-Id", required = false) String requestId,
        @RequestParam(value = "company_id", required = false) String companyId,
        @RequestParam(value = "org_id", required = false) String orgId
    ) {
        return aiGatewayService
            .getConversationMessages(authorization, requestId, agentId, sessionId, companyId, orgId)
            .stream()
            .map(row -> new ConversationMessageResponse(row.role(), row.message_text(), row.created_at(), row.intent_label()))
            .toList();
    }

    @PostMapping("/agents/{agentId}/conversations/{sessionId}/reply")
    public ConversationReplyResponse replyToConversation(
        @PathVariable String agentId,
        @PathVariable String sessionId,
        @Valid @RequestBody ConversationReplyRequest request,
        @RequestHeader(value = "Authorization", required = false) String authorization,
        @RequestHeader(value = "X-Request-Id", required = false) String requestId,
        @RequestParam(value = "company_id", required = false) String companyId,
        @RequestParam(value = "org_id", required = false) String orgId
    ) {
        var response = aiGatewayService.replyToConversation(
            authorization, requestId, agentId, sessionId, companyId, orgId,
            new com.clasificacion.platformapi.ai.contract.AiConversationReplyRequest(request.message())
        );
        return new ConversationReplyResponse(response.delivered(), response.channel());
    }

    @PostMapping("/agents/{agentId}/conversations/{sessionId}/takeover")
    public ConversationStatusResponse takeoverConversation(
        @PathVariable String agentId,
        @PathVariable String sessionId,
        @RequestHeader(value = "Authorization", required = false) String authorization,
        @RequestHeader(value = "X-Request-Id", required = false) String requestId,
        @RequestParam(value = "company_id", required = false) String companyId,
        @RequestParam(value = "org_id", required = false) String orgId
    ) {
        var response = aiGatewayService.takeoverConversation(authorization, requestId, agentId, sessionId, companyId, orgId);
        return new ConversationStatusResponse(response.session_id(), response.status());
    }

    @PostMapping("/agents/{agentId}/conversations/{sessionId}/release")
    public ConversationStatusResponse releaseConversation(
        @PathVariable String agentId,
        @PathVariable String sessionId,
        @RequestHeader(value = "Authorization", required = false) String authorization,
        @RequestHeader(value = "X-Request-Id", required = false) String requestId,
        @RequestParam(value = "company_id", required = false) String companyId,
        @RequestParam(value = "org_id", required = false) String orgId
    ) {
        var response = aiGatewayService.releaseConversation(authorization, requestId, agentId, sessionId, companyId, orgId);
        return new ConversationStatusResponse(response.session_id(), response.status());
    }

    /**
     * Streaming SSE de la lista de conversaciones de un agente. EventSource nativo del
     * navegador no puede mandar headers custom, por eso acepta el JWT tambien como
     * access_token de query (mismo alcance que el header Authorization de siempre).
     * Reemplaza el polling por setInterval del frontend: en vez de que el browser
     * pregunte cada 8s, este endpoint pregunta el cada 2s del lado del server y solo
     * empuja un evento cuando el resultado cambio.
     */
    @GetMapping(path = "/agents/{agentId}/conversations/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter streamConversations(
        @PathVariable String agentId,
        @RequestHeader(value = "Authorization", required = false) String authorization,
        @RequestParam(value = "access_token", required = false) String accessToken,
        @RequestParam(value = "company_id", required = false) String companyId,
        @RequestParam(value = "org_id", required = false) String orgId,
        @RequestParam(value = "status", required = false) String status,
        @RequestParam(value = "limit", required = false, defaultValue = "50") int limit
    ) {
        String effectiveAuthorization = resolveAuthorization(authorization, accessToken);
        SseEmitter emitter = new SseEmitter(CONVERSATION_STREAM_TIMEOUT_MS);
        AtomicReference<String> lastFingerprint = new AtomicReference<>(null);

        ScheduledFuture<?> task = conversationStreamScheduler.scheduleWithFixedDelay(() -> {
            try {
                var rows = aiGatewayService.listConversations(
                    effectiveAuthorization, null, agentId, companyId, orgId, status, limit
                );
                String fingerprint = rows.stream()
                    .map(row -> row.session_id() + ":" + row.status() + ":" + row.message_count() + ":" + row.updated_at())
                    .reduce("", (a, b) -> a + "|" + b);
                if (!fingerprint.equals(lastFingerprint.get())) {
                    lastFingerprint.set(fingerprint);
                    var payload = rows.stream()
                        .map(row -> new ConversationSummaryResponse(
                            row.session_id(),
                            row.channel(),
                            row.status(),
                            row.message_count(),
                            row.started_at(),
                            row.updated_at(),
                            row.visitor_id(),
                            row.external_user_id(),
                            row.authenticated_user_id(),
                            row.last_message_preview()
                        ))
                        .toList();
                    emitter.send(SseEmitter.event().name("update").data(writeJsonQuietly(payload), MediaType.APPLICATION_JSON));
                }
            } catch (Exception exc) {
                log.warn("conversation_stream_poll_error agent_id={} error={}", agentId, exc.getMessage());
                emitter.completeWithError(exc);
            }
        }, 0, CONVERSATION_STREAM_POLL_MS, TimeUnit.MILLISECONDS);

        emitter.onCompletion(() -> task.cancel(true));
        emitter.onTimeout(() -> task.cancel(true));
        emitter.onError((exc) -> task.cancel(true));
        return emitter;
    }

    /**
     * Streaming SSE de los mensajes de una conversacion puntual. Mismo patron que
     * streamConversations: poll cada 2s contra Python via aiGatewayService, push solo
     * si cambio.
     */
    @GetMapping(
        path = "/agents/{agentId}/conversations/{sessionId}/messages/stream",
        produces = MediaType.TEXT_EVENT_STREAM_VALUE
    )
    public SseEmitter streamConversationMessages(
        @PathVariable String agentId,
        @PathVariable String sessionId,
        @RequestHeader(value = "Authorization", required = false) String authorization,
        @RequestParam(value = "access_token", required = false) String accessToken,
        @RequestParam(value = "company_id", required = false) String companyId,
        @RequestParam(value = "org_id", required = false) String orgId
    ) {
        String effectiveAuthorization = resolveAuthorization(authorization, accessToken);
        SseEmitter emitter = new SseEmitter(CONVERSATION_STREAM_TIMEOUT_MS);
        AtomicReference<String> lastFingerprint = new AtomicReference<>(null);

        ScheduledFuture<?> task = conversationStreamScheduler.scheduleWithFixedDelay(() -> {
            try {
                var rows = aiGatewayService.getConversationMessages(
                    effectiveAuthorization, null, agentId, sessionId, companyId, orgId
                );
                String fingerprint = rows.size() + ":" + (rows.isEmpty() ? "" : rows.get(rows.size() - 1).created_at());
                if (!fingerprint.equals(lastFingerprint.get())) {
                    lastFingerprint.set(fingerprint);
                    var payload = rows.stream()
                        .map(row -> new ConversationMessageResponse(row.role(), row.message_text(), row.created_at(), row.intent_label()))
                        .toList();
                    emitter.send(SseEmitter.event().name("update").data(writeJsonQuietly(payload), MediaType.APPLICATION_JSON));
                }
            } catch (Exception exc) {
                log.warn("conversation_messages_stream_poll_error agent_id={} session_id={} error={}", agentId, sessionId, exc.getMessage());
                emitter.completeWithError(exc);
            }
        }, 0, CONVERSATION_STREAM_POLL_MS, TimeUnit.MILLISECONDS);

        emitter.onCompletion(() -> task.cancel(true));
        emitter.onTimeout(() -> task.cancel(true));
        emitter.onError((exc) -> task.cancel(true));
        return emitter;
    }

    /**
     * Solo se respeta un X-Public-Base-Url EXPLICITO (p. ej. para pruebas). El Origin/Referer
     * de este request es el de quien pide la config (la consola), no el del AI Engine: usarlo
     * como base publica del widget o del webhook de WhatsApp apuntaria al dominio equivocado.
     * Sin override, AiGatewayService aplica su propio default (app.ai-engine.public-base-url).
     */
    private String resolvePublicBaseUrl(HttpServletRequest request) {
        String explicitPublicBase = request.getHeader("X-Public-Base-Url");
        if (explicitPublicBase != null && !explicitPublicBase.isBlank()) {
            return explicitPublicBase.strip();
        }
        return null;
    }
}
