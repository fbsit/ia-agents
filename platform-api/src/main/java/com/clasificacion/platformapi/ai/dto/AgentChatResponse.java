package com.clasificacion.platformapi.ai.dto;

import java.util.List;

public record AgentChatResponse(
    String agent_id,
    String company_id,
    String session_id,
    String answer,
    List<String> sources,
    String intent_label,
    String route,
    String route_reason,
    String response_mode,
    boolean fallback_applied,
    Double retrieval_min_score,
    String redirect_to
) {
}
