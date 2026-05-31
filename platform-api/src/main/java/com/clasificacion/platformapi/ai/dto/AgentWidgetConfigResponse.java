package com.clasificacion.platformapi.ai.dto;

import java.util.List;

public record AgentWidgetConfigResponse(
    String agent_id,
    String widget_id,
    String endpoint_url,
    String widget_token,
    List<String> allowed_origins,
    int rate_limit_window_seconds,
    int rate_limit_max_requests,
    String snippet_html
) {
}
