package com.clasificacion.platformapi.ai.dto;

import jakarta.validation.constraints.NotBlank;

public record ConversationReplyRequest(
    @NotBlank String message
) {
}
