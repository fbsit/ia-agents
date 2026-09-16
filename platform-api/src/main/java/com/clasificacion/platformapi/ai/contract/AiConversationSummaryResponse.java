package com.clasificacion.platformapi.ai.contract;

public record AiConversationSummaryResponse(
    String session_id,
    String channel,
    String status,
    int message_count,
    String started_at,
    String updated_at,
    String visitor_id,
    String external_user_id,
    String authenticated_user_id,
    String last_message_preview
) {
}
