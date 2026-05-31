package com.clasificacion.platformapi.ai.dto;

import java.util.List;

public record AgentWhatsAppValidationResponse(
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
