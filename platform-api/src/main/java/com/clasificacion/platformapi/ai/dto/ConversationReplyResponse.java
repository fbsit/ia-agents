package com.clasificacion.platformapi.ai.dto;

public record ConversationReplyResponse(
    boolean delivered,
    String channel
) {
}
