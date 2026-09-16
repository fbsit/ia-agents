package com.clasificacion.platformapi.ai.contract;

public record AiConversationReplyResponse(
    boolean delivered,
    String channel
) {
}
