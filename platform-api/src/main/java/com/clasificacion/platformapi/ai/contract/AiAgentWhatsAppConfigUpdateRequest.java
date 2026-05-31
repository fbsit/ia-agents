package com.clasificacion.platformapi.ai.contract;

public record AiAgentWhatsAppConfigUpdateRequest(
    String phone_number_id,
    String business_account_id,
    String verify_token
) {
}
