package com.clasificacion.platformapi.ai.contract;

import java.util.List;
import java.util.Map;

public record AiAgentChatResponse(
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
    String redirect_to,
    Map<String, Object> cart_action,
    List<Map<String, Object>> cart_actions,
    List<Map<String, Object>> products
) {
}
