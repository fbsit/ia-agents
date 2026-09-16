package com.clasificacion.platformapi.ai.dto;

public record ConversationMessageResponse(
    String role,
    String message_text,
    String created_at,
    String intent_label
) {
}
