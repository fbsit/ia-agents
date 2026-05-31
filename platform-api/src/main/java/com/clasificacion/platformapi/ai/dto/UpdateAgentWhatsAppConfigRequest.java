package com.clasificacion.platformapi.ai.dto;

public record UpdateAgentWhatsAppConfigRequest(
    String phone_number_id,
    String business_account_id,
    String verify_token,
    String company_id,
    String org_id
) {
}
