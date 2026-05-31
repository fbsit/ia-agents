package com.clasificacion.platformapi.ai.config;

import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;

@ConfigurationProperties(prefix = "app.ai-engine")
public record AiEngineProperties(
    String baseUrl,
    String pathPrefix,
    Duration connectTimeout,
    Duration readTimeout,
    String sharedSecret
) {
    public AiEngineProperties {
        baseUrl = baseUrl == null || baseUrl.isBlank()
            ? "http://localhost:8000"
            : baseUrl;
        pathPrefix = pathPrefix == null || pathPrefix.isBlank() ? "" : pathPrefix;
        connectTimeout = connectTimeout == null ? Duration.ofSeconds(3) : connectTimeout;
        readTimeout = readTimeout == null ? Duration.ofSeconds(30) : readTimeout;
        sharedSecret = sharedSecret == null ? "" : sharedSecret;
    }

    public String normalizedPathPrefix() {
        if (pathPrefix.isBlank()) {
            return "";
        }
        if (pathPrefix.startsWith("/")) {
            return pathPrefix;
        }
        return "/" + pathPrefix;
    }
}
