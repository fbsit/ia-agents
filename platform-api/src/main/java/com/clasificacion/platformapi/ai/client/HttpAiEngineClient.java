package com.clasificacion.platformapi.ai.client;

import com.clasificacion.platformapi.ai.config.AiEngineProperties;
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
import com.clasificacion.platformapi.ai.contract.AiConversationMessageResponse;
import com.clasificacion.platformapi.ai.contract.AiConversationReplyRequest;
import com.clasificacion.platformapi.ai.contract.AiConversationReplyResponse;
import com.clasificacion.platformapi.ai.contract.AiConversationStatusResponse;
import com.clasificacion.platformapi.ai.contract.AiConversationSummaryResponse;
import com.clasificacion.platformapi.ai.contract.AiDeleteResponse;
import com.clasificacion.platformapi.ai.contract.AiDocumentDeleteResponse;
import com.clasificacion.platformapi.ai.contract.AiEngineHeaders;
import com.clasificacion.platformapi.ai.contract.AiErrorResponse;
import com.clasificacion.platformapi.ai.contract.AiMediaTranscriptionRequest;
import com.clasificacion.platformapi.ai.contract.AiMediaTranscriptionResponse;
import com.clasificacion.platformapi.ai.contract.AiTenantLlmSettingsResponse;
import com.clasificacion.platformapi.ai.contract.AiTenantLlmSettingsUpdateRequest;
import com.clasificacion.platformapi.ai.contract.AiRuntimeExecuteRequest;
import com.clasificacion.platformapi.ai.contract.AiRuntimeExecuteResponse;
import com.clasificacion.platformapi.ai.exception.AiEngineException;
import com.clasificacion.platformapi.ai.service.AiRequestContext;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.Arrays;
import java.util.List;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;

@Component
public class HttpAiEngineClient implements AiEngineClient {
    private static final Logger log = LoggerFactory.getLogger(HttpAiEngineClient.class);
    private final RestClient restClient;
    private final ObjectMapper objectMapper;
    private final AiEngineProperties properties;

    public HttpAiEngineClient(
        RestClient.Builder restClientBuilder,
        ObjectMapper objectMapper,
        AiEngineProperties properties
    ) {
        this.objectMapper = objectMapper;
        this.properties = properties;

        SimpleClientHttpRequestFactory requestFactory = new SimpleClientHttpRequestFactory();
        requestFactory.setConnectTimeout((int) properties.connectTimeout().toMillis());
        requestFactory.setReadTimeout((int) properties.readTimeout().toMillis());

        this.restClient = restClientBuilder
            .baseUrl(properties.baseUrl())
            .requestFactory(requestFactory)
            .build();
    }

    @Override
    public AiAgentResponse createAgent(AiRequestContext context, AiAgentCreateRequest payload) {
        String uri = buildUri("/internal/ai/agents");
        try {
            return restClient.post()
                .uri(uri)
                .headers(headers -> enrichHeaders(headers, context))
                .body(payload)
                .retrieve()
                .body(AiAgentResponse.class);
        } catch (RestClientResponseException exc) {
            throw mapError(exc);
        }
    }

    @Override
    public List<AiAgentResponse> listAgents(AiRequestContext context) {
        String uri = buildUri("/internal/ai/agents");
        try {
            AiAgentResponse[] payload = restClient.get()
                .uri(uri)
                .headers(headers -> enrichHeaders(headers, context))
                .retrieve()
                .body(AiAgentResponse[].class);
            return payload == null ? List.of() : Arrays.asList(payload);
        } catch (RestClientResponseException exc) {
            throw mapError(exc);
        }
    }

    @Override
    public AiAgentResponse updateAgent(AiRequestContext context, String agentId, AiAgentUpdateRequest payload) {
        String uri = buildUri("/internal/ai/agents/" + agentId);
        try {
            return restClient.patch()
                .uri(uri)
                .headers(headers -> enrichHeaders(headers, context))
                .body(payload)
                .retrieve()
                .body(AiAgentResponse.class);
        } catch (RestClientResponseException exc) {
            throw mapError(exc);
        }
    }

    @Override
    public AiDeleteResponse deleteAgent(AiRequestContext context, String agentId) {
        String uri = buildUri("/internal/ai/agents/" + agentId);
        try {
            return restClient.delete()
                .uri(uri)
                .headers(headers -> enrichHeaders(headers, context))
                .retrieve()
                .body(AiDeleteResponse.class);
        } catch (RestClientResponseException exc) {
            throw mapError(exc);
        }
    }

    @Override
    public List<AiAgentDocumentResponse> listAgentDocuments(AiRequestContext context, String agentId) {
        String uri = buildUri("/internal/ai/agents/" + agentId + "/documents");
        try {
            AiAgentDocumentResponse[] payload = restClient.get()
                .uri(uri)
                .headers(headers -> enrichHeaders(headers, context))
                .retrieve()
                .body(AiAgentDocumentResponse[].class);
            return payload == null ? List.of() : Arrays.asList(payload);
        } catch (RestClientResponseException exc) {
            throw mapError(exc);
        }
    }

    @Override
    public AiAgentDocumentResponse uploadAgentDocument(
        AiRequestContext context,
        String agentId,
        AiAgentDocumentUploadRequest payload
    ) {
        String uri = buildUri("/internal/ai/agents/" + agentId + "/documents");
        try {
            return restClient.post()
                .uri(uri)
                .headers(headers -> enrichHeaders(headers, context))
                .body(payload)
                .retrieve()
                .body(AiAgentDocumentResponse.class);
        } catch (RestClientResponseException exc) {
            throw mapError(exc);
        }
    }

    @Override
    public AiMediaTranscriptionResponse transcribeMedia(
        AiRequestContext context,
        AiMediaTranscriptionRequest payload
    ) {
        String uri = buildUri("/internal/ai/media/transcriptions");
        log.info("ai_transcribe_request tenant_id={} org_id={} uri={}", context.companyId(), context.orgId(), uri);
        try {
            return restClient.post()
                .uri(uri)
                .headers(headers -> enrichHeaders(headers, context))
                .body(payload)
                .retrieve()
                .body(AiMediaTranscriptionResponse.class);
        } catch (RestClientResponseException exc) {
            String responseBody = exc.getResponseBodyAsString();
            String cleanBody = responseBody == null ? "" : responseBody.replaceAll("\\s+", " ");
            log.warn(
                "ai_transcribe_failed status={} uri={} body={}",
                exc.getRawStatusCode(),
                uri,
                cleanBody.substring(0, Math.min(500, cleanBody.length()))
            );
            throw mapError(exc);
        }
    }

    @Override
    public AiDocumentDeleteResponse deleteAgentDocument(
        AiRequestContext context,
        String agentId,
        String documentId
    ) {
        String uri = buildUri("/internal/ai/agents/" + agentId + "/documents/" + documentId);
        try {
            return restClient.delete()
                .uri(uri)
                .headers(headers -> enrichHeaders(headers, context))
                .retrieve()
                .body(AiDocumentDeleteResponse.class);
        } catch (RestClientResponseException exc) {
            throw mapError(exc);
        }
    }

    @Override
    public AiAgentIndexResponse rebuildAgentIndex(AiRequestContext context, String agentId) {
        String uri = buildUri("/internal/ai/agents/" + agentId + "/index/rebuild");
        try {
            return restClient.post()
                .uri(uri)
                .headers(headers -> enrichHeaders(headers, context))
                .retrieve()
                .body(AiAgentIndexResponse.class);
        } catch (RestClientResponseException exc) {
            throw mapError(exc);
        }
    }

    @Override
    public AiAgentIndexStatusResponse getAgentIndexStatus(AiRequestContext context, String agentId) {
        String uri = buildUri("/internal/ai/agents/" + agentId + "/index/status");
        try {
            return restClient.get()
                .uri(uri)
                .headers(headers -> enrichHeaders(headers, context))
                .retrieve()
                .body(AiAgentIndexStatusResponse.class);
        } catch (RestClientResponseException exc) {
            throw mapError(exc);
        }
    }

    @Override
    public AiAgentSetupStatusResponse getAgentSetupStatus(AiRequestContext context, String agentId) {
        String uri = buildUri("/internal/ai/agents/" + agentId + "/setup-status");
        try {
            return restClient.get()
                .uri(uri)
                .headers(headers -> enrichHeaders(headers, context))
                .retrieve()
                .body(AiAgentSetupStatusResponse.class);
        } catch (RestClientResponseException exc) {
            throw mapError(exc);
        }
    }

    @Override
    public AiAgentWidgetConfigResponse getAgentWidgetConfig(
        AiRequestContext context,
        String agentId,
        String publicBaseUrl
    ) {
        String uri = buildUri("/internal/ai/agents/" + agentId + "/widget-config");
        try {
            return restClient.get()
                .uri(uri)
                .headers(headers -> enrichHeaders(headers, context, publicBaseUrl))
                .retrieve()
                .body(AiAgentWidgetConfigResponse.class);
        } catch (RestClientResponseException exc) {
            throw mapError(exc);
        }
    }

    @Override
    public AiAgentWhatsAppConfigResponse getAgentWhatsAppConfig(
        AiRequestContext context,
        String agentId,
        String publicBaseUrl
    ) {
        String uri = buildUri("/internal/ai/agents/" + agentId + "/channels/whatsapp/config");
        try {
            return restClient.get()
                .uri(uri)
                .headers(headers -> enrichHeaders(headers, context, publicBaseUrl))
                .retrieve()
                .body(AiAgentWhatsAppConfigResponse.class);
        } catch (RestClientResponseException exc) {
            throw mapError(exc);
        }
    }

    @Override
    public AiAgentWhatsAppConfigResponse updateAgentWhatsAppConfig(
        AiRequestContext context,
        String agentId,
        AiAgentWhatsAppConfigUpdateRequest payload,
        String publicBaseUrl
    ) {
        String uri = buildUri("/internal/ai/agents/" + agentId + "/channels/whatsapp/config");
        try {
            return restClient.put()
                .uri(uri)
                .headers(headers -> enrichHeaders(headers, context, publicBaseUrl))
                .body(payload)
                .retrieve()
                .body(AiAgentWhatsAppConfigResponse.class);
        } catch (RestClientResponseException exc) {
            throw mapError(exc);
        }
    }

    @Override
    public AiAgentWhatsAppValidationResponse validateAgentWhatsAppConfig(
        AiRequestContext context,
        String agentId,
        String publicBaseUrl
    ) {
        String uri = buildUri("/internal/ai/agents/" + agentId + "/channels/whatsapp/validate");
        try {
            return restClient.post()
                .uri(uri)
                .headers(headers -> enrichHeaders(headers, context, publicBaseUrl))
                .retrieve()
                .body(AiAgentWhatsAppValidationResponse.class);
        } catch (RestClientResponseException exc) {
            throw mapError(exc);
        }
    }

    @Override
    public AiAgentFeedbackSummaryResponse getAgentFeedbackSummary(
        AiRequestContext context,
        String agentId,
        int days
    ) {
        String uri = buildUri("/internal/ai/agents/" + agentId + "/feedback/summary?days=" + days);
        try {
            return restClient.get()
                .uri(uri)
                .headers(headers -> enrichHeaders(headers, context))
                .retrieve()
                .body(AiAgentFeedbackSummaryResponse.class);
        } catch (RestClientResponseException exc) {
            throw mapError(exc);
        }
    }

    @Override
    public AiAgentChatResponse chatAgent(AiRequestContext context, String agentId, AiAgentChatRequest payload) {
        String uri = buildUri("/internal/ai/agents/" + agentId + "/chat");
        try {
            return restClient.post()
                .uri(uri)
                .headers(headers -> enrichHeaders(headers, context))
                .body(payload)
                .retrieve()
                .body(AiAgentChatResponse.class);
        } catch (RestClientResponseException exc) {
            throw mapError(exc);
        }
    }

    @Override
    public AiTenantLlmSettingsResponse getTenantLlmSettings(AiRequestContext context) {
        String uri = buildUri("/internal/ai/settings/llm");
        try {
            return restClient.get()
                .uri(uri)
                .headers(headers -> enrichHeaders(headers, context))
                .retrieve()
                .body(AiTenantLlmSettingsResponse.class);
        } catch (RestClientResponseException exc) {
            throw mapError(exc);
        }
    }

    @Override
    public AiTenantLlmSettingsResponse updateTenantLlmSettings(
        AiRequestContext context,
        AiTenantLlmSettingsUpdateRequest payload
    ) {
        String uri = buildUri("/internal/ai/settings/llm");
        try {
            return restClient.put()
                .uri(uri)
                .headers(headers -> enrichHeaders(headers, context))
                .body(payload)
                .retrieve()
                .body(AiTenantLlmSettingsResponse.class);
        } catch (RestClientResponseException exc) {
            throw mapError(exc);
        }
    }

    @Override
    public AiRuntimeExecuteResponse executePublishedSkill(
        AiRequestContext context,
        String skillId,
        AiRuntimeExecuteRequest payload
    ) {
        String uri = buildUri("/internal/ai/runtime/skills/" + skillId + "/execute");
        try {
            return restClient.post()
                .uri(uri)
                .headers(headers -> enrichHeaders(headers, context))
                .body(payload)
                .retrieve()
                .body(AiRuntimeExecuteResponse.class);
        } catch (RestClientResponseException exc) {
            throw mapError(exc);
        }
    }

    @Override
    public AiRuntimeExecuteResponse executePublishedFlow(
        AiRequestContext context,
        String flowId,
        AiRuntimeExecuteRequest payload
    ) {
        String uri = buildUri("/internal/ai/runtime/flows/" + flowId + "/execute");
        try {
            return restClient.post()
                .uri(uri)
                .headers(headers -> enrichHeaders(headers, context))
                .body(payload)
                .retrieve()
                .body(AiRuntimeExecuteResponse.class);
        } catch (RestClientResponseException exc) {
            throw mapError(exc);
        }
    }

    @Override
    public List<AiConversationSummaryResponse> listConversations(
        AiRequestContext context,
        String agentId,
        String status,
        int limit
    ) {
        StringBuilder path = new StringBuilder("/internal/ai/agents/" + agentId + "/conversations?limit=" + limit);
        if (status != null && !status.isBlank()) {
            path.append("&status=").append(status);
        }
        String uri = buildUri(path.toString());
        try {
            AiConversationSummaryResponse[] payload = restClient.get()
                .uri(uri)
                .headers(headers -> enrichHeaders(headers, context))
                .retrieve()
                .body(AiConversationSummaryResponse[].class);
            return payload == null ? List.of() : Arrays.asList(payload);
        } catch (RestClientResponseException exc) {
            throw mapError(exc);
        }
    }

    @Override
    public List<AiConversationMessageResponse> getConversationMessages(
        AiRequestContext context,
        String agentId,
        String sessionId
    ) {
        String uri = buildUri("/internal/ai/agents/" + agentId + "/conversations/" + sessionId + "/messages");
        try {
            AiConversationMessageResponse[] payload = restClient.get()
                .uri(uri)
                .headers(headers -> enrichHeaders(headers, context))
                .retrieve()
                .body(AiConversationMessageResponse[].class);
            return payload == null ? List.of() : Arrays.asList(payload);
        } catch (RestClientResponseException exc) {
            throw mapError(exc);
        }
    }

    @Override
    public AiConversationReplyResponse replyToConversation(
        AiRequestContext context,
        String agentId,
        String sessionId,
        AiConversationReplyRequest payload
    ) {
        String uri = buildUri("/internal/ai/agents/" + agentId + "/conversations/" + sessionId + "/reply");
        try {
            return restClient.post()
                .uri(uri)
                .headers(headers -> enrichHeaders(headers, context))
                .body(payload)
                .retrieve()
                .body(AiConversationReplyResponse.class);
        } catch (RestClientResponseException exc) {
            throw mapError(exc);
        }
    }

    @Override
    public AiConversationStatusResponse takeoverConversation(AiRequestContext context, String agentId, String sessionId) {
        String uri = buildUri("/internal/ai/agents/" + agentId + "/conversations/" + sessionId + "/takeover");
        try {
            return restClient.post()
                .uri(uri)
                .headers(headers -> enrichHeaders(headers, context))
                .retrieve()
                .body(AiConversationStatusResponse.class);
        } catch (RestClientResponseException exc) {
            throw mapError(exc);
        }
    }

    @Override
    public AiConversationStatusResponse releaseConversation(AiRequestContext context, String agentId, String sessionId) {
        String uri = buildUri("/internal/ai/agents/" + agentId + "/conversations/" + sessionId + "/release");
        try {
            return restClient.post()
                .uri(uri)
                .headers(headers -> enrichHeaders(headers, context))
                .retrieve()
                .body(AiConversationStatusResponse.class);
        } catch (RestClientResponseException exc) {
            throw mapError(exc);
        }
    }

    private void enrichHeaders(org.springframework.http.HttpHeaders headers, AiRequestContext context) {
        headers.set(AiEngineHeaders.COMPANY_ID, context.companyId());
        headers.set(AiEngineHeaders.ORG_ID, context.orgId());
        headers.set(AiEngineHeaders.USER_ID, context.userId());
        headers.set(AiEngineHeaders.REQUEST_ID, context.requestId());
        if (!properties.sharedSecret().isBlank()) {
            String timestamp = String.valueOf(Instant.now().getEpochSecond());
            headers.set(AiEngineHeaders.TIMESTAMP, timestamp);
            headers.set(
                AiEngineHeaders.SIGNATURE,
                signContext(properties.sharedSecret(), timestamp, context)
            );
        }
    }

    private void enrichHeaders(
        org.springframework.http.HttpHeaders headers,
        AiRequestContext context,
        String publicBaseUrl
    ) {
        enrichHeaders(headers, context);
        if (publicBaseUrl != null && !publicBaseUrl.isBlank()) {
            headers.set("X-Public-Base-Url", publicBaseUrl);
        }
    }

    private String signContext(String secret, String timestamp, AiRequestContext context) {
        String canonical = String.join(
            "\n",
            timestamp,
            context.companyId(),
            context.orgId(),
            context.userId(),
            context.requestId()
        );
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            SecretKeySpec key = new SecretKeySpec(secret.getBytes(StandardCharsets.UTF_8), "HmacSHA256");
            mac.init(key);
            byte[] digest = mac.doFinal(canonical.getBytes(StandardCharsets.UTF_8));
            StringBuilder builder = new StringBuilder(digest.length * 2);
            for (byte item : digest) {
                builder.append(String.format("%02x", item));
            }
            return builder.toString();
        } catch (Exception exc) {
            throw new IllegalStateException("No se pudo firmar request interna", exc);
        }
    }

    private String buildUri(String path) {
        return properties.normalizedPathPrefix() + path;
    }

    private AiEngineException mapError(RestClientResponseException exc) {
        String requestId = "";
        String code = "AI_ENGINE_ERROR";
        String detail = "Error llamando ai-engine";

        String body = exc.getResponseBodyAsString();
        if (body != null && !body.isBlank()) {
            try {
                AiErrorResponse error = objectMapper.readValue(body, AiErrorResponse.class);
                if (error.request_id() != null && !error.request_id().isBlank()) {
                    requestId = error.request_id();
                }
                if (error.code() != null && !error.code().isBlank()) {
                    code = error.code();
                }
                if (error.detail() != null && !error.detail().isBlank()) {
                    detail = error.detail();
                }
            } catch (Exception ignored) {
                detail = body;
            }
        }

        return new AiEngineException(exc.getStatusCode().value(), code, detail, requestId);
    }
}
