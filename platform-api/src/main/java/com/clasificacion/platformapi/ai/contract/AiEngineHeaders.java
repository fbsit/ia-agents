package com.clasificacion.platformapi.ai.contract;

public final class AiEngineHeaders {
    public static final String COMPANY_ID = "X-Company-Id";
    public static final String ORG_ID = "X-Org-Id";
    public static final String USER_ID = "X-User-Id";
    public static final String REQUEST_ID = "X-Request-Id";
    public static final String SIGNATURE = "X-Platform-Signature";
    public static final String TIMESTAMP = "X-Platform-Timestamp";

    private AiEngineHeaders() {
    }
}
