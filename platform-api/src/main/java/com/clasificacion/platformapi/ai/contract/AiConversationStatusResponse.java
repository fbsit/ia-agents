package com.clasificacion.platformapi.ai.contract;

public record AiConversationStatusResponse(
    String session_id,
    String status
) {
}
