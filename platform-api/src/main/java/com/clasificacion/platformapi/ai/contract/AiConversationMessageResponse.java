package com.clasificacion.platformapi.ai.contract;

public record AiConversationMessageResponse(
    String role,
    String message_text,
    String created_at,
    String intent_label
) {
}
