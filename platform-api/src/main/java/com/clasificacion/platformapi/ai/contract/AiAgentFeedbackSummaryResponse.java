package com.clasificacion.platformapi.ai.contract;

public record AiAgentFeedbackSummaryResponse(
    String company_id,
    String agent_id,
    int feedback_total,
    int thumbs_up,
    int thumbs_down,
    double positive_rate,
    int with_comment,
    int with_expected_answer
) {
}
