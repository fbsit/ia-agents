package com.clasificacion.platformapi.ai.controller;

import com.clasificacion.platformapi.ai.exception.AiEngineException;
import java.util.LinkedHashMap;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice(assignableTypes = AgentsController.class)
public class AiProxyErrorHandler {
    @ExceptionHandler(AiEngineException.class)
    public ResponseEntity<Map<String, String>> handleAiEngineError(AiEngineException exc) {
        HttpStatus status = HttpStatus.resolve(exc.statusCode());
        if (status == null) {
            status = HttpStatus.BAD_GATEWAY;
        }

        Map<String, String> body = new LinkedHashMap<>();
        body.put("detail", exc.getMessage());
        if (exc.errorCode() != null && !exc.errorCode().isBlank()) {
            body.put("code", exc.errorCode());
        }
        if (exc.requestId() != null && !exc.requestId().isBlank()) {
            body.put("request_id", exc.requestId());
        }
        return ResponseEntity.status(status).body(body);
    }

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<Map<String, String>> handleBadInput(IllegalArgumentException exc) {
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(Map.of("detail", exc.getMessage()));
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<Map<String, String>> handleValidation(MethodArgumentNotValidException exc) {
        String message = exc.getBindingResult().getFieldErrors().stream()
            .findFirst()
            .map(fieldError -> fieldError.getField() + " invalido")
            .orElse("Payload invalido");
        return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(Map.of("detail", message));
    }
}
