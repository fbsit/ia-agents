package com.clasificacion.platformapi.ai.client;

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
import com.clasificacion.platformapi.ai.contract.AiRuntimeExecuteRequest;
import com.clasificacion.platformapi.ai.contract.AiRuntimeExecuteResponse;
import com.clasificacion.platformapi.ai.service.AiRequestContext;
import java.util.List;

public interface AiEngineClient {
    AiAgentResponse createAgent(AiRequestContext context, AiAgentCreateRequest payload);

    List<AiAgentResponse> listAgents(AiRequestContext context);

    AiAgentResponse updateAgent(AiRequestContext context, String agentId, AiAgentUpdateRequest payload);

    AiDeleteResponse deleteAgent(AiRequestContext context, String agentId);

    List<AiAgentDocumentResponse> listAgentDocuments(AiRequestContext context, String agentId);

    AiAgentDocumentResponse uploadAgentDocument(
        AiRequestContext context,
        String agentId,
        AiAgentDocumentUploadRequest payload
    );

    AiDocumentDeleteResponse deleteAgentDocument(
        AiRequestContext context,
        String agentId,
        String documentId
    );

    AiAgentIndexResponse rebuildAgentIndex(AiRequestContext context, String agentId);

    AiAgentIndexStatusResponse getAgentIndexStatus(AiRequestContext context, String agentId);

    AiAgentSetupStatusResponse getAgentSetupStatus(AiRequestContext context, String agentId);

    AiAgentWidgetConfigResponse getAgentWidgetConfig(
        AiRequestContext context,
        String agentId,
        String publicBaseUrl
    );

    AiAgentWhatsAppConfigResponse getAgentWhatsAppConfig(
        AiRequestContext context,
        String agentId,
        String publicBaseUrl
    );

    AiAgentWhatsAppConfigResponse updateAgentWhatsAppConfig(
        AiRequestContext context,
        String agentId,
        AiAgentWhatsAppConfigUpdateRequest payload,
        String publicBaseUrl
    );

    AiAgentWhatsAppValidationResponse validateAgentWhatsAppConfig(
        AiRequestContext context,
        String agentId,
        String publicBaseUrl
    );

    AiAgentFeedbackSummaryResponse getAgentFeedbackSummary(
        AiRequestContext context,
        String agentId,
        int days
    );

    AiAgentChatResponse chatAgent(AiRequestContext context, String agentId, AiAgentChatRequest payload);

    AiTenantLlmSettingsResponse getTenantLlmSettings(AiRequestContext context);

    AiTenantLlmSettingsResponse updateTenantLlmSettings(
        AiRequestContext context,
        AiTenantLlmSettingsUpdateRequest payload
    );

    AiRuntimeExecuteResponse executePublishedSkill(
        AiRequestContext context,
        String skillId,
        AiRuntimeExecuteRequest payload
    );

    AiRuntimeExecuteResponse executePublishedFlow(
        AiRequestContext context,
        String flowId,
        AiRuntimeExecuteRequest payload
    );
}
