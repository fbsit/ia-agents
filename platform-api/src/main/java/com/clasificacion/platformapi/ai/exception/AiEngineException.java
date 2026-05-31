package com.clasificacion.platformapi.ai.exception;

public class AiEngineException extends RuntimeException {
    private final int statusCode;
    private final String errorCode;
    private final String requestId;

    public AiEngineException(int statusCode, String errorCode, String detail, String requestId) {
        super(detail);
        this.statusCode = statusCode;
        this.errorCode = errorCode;
        this.requestId = requestId;
    }

    public int statusCode() {
        return statusCode;
    }

    public String errorCode() {
        return errorCode;
    }

    public String requestId() {
        return requestId;
    }
}
