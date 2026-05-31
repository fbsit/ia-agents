package com.clasificacion.platformapi.catalog.controller;

import com.clasificacion.platformapi.catalog.exception.CatalogException;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public class CatalogErrorHandler {
    @ExceptionHandler(CatalogException.class)
    public ResponseEntity<Map<String, String>> handleCatalog(CatalogException exc) {
        return ResponseEntity.status(exc.status()).body(Map.of("detail", exc.getMessage()));
    }
}
