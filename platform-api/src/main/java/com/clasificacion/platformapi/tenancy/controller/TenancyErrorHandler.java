package com.clasificacion.platformapi.tenancy.controller;

import com.clasificacion.platformapi.tenancy.exception.TenancyException;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public class TenancyErrorHandler {
    @ExceptionHandler(TenancyException.class)
    public ResponseEntity<Map<String, String>> handleConflict(TenancyException exc) {
        return ResponseEntity.status(HttpStatus.CONFLICT).body(Map.of("detail", exc.getMessage()));
    }
}
