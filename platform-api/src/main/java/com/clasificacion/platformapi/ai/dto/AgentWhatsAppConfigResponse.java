package com.clasificacion.platformapi.ai.dto;

public record AgentWhatsAppConfigResponse(
    String agent_id,
    String company_id,
    String webhook_url,
    String phone_number_id,
    String business_account_id,
    String verify_token,
    String updated_at
) {
}
