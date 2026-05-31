package com.clasificacion.platformapi.ai.contract;

import java.util.List;

public record AiAgentWhatsAppValidationResponse(
    String agent_id,
    String company_id,
    boolean ready,
    boolean has_phone_number_id,
    boolean has_verify_token,
    boolean server_has_access_token,
    boolean company_map_ready,
    String webhook_url,
    List<String> messages
) {
}
