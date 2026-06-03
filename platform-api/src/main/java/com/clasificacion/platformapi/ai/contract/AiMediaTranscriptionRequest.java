package com.clasificacion.platformapi.ai.contract;

public record AiMediaTranscriptionRequest(
    String filename,
    String content_base64,
    String mime_type,
    String language_hint,
    String channel,
    String source,
    String session_id,
    String conversation_id,
    String phone_number_id
) {
}
