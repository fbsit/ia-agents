package com.clasificacion.platformapi.auth.controller;

import com.clasificacion.platformapi.auth.exception.EmailAlreadyExistsException;
import com.clasificacion.platformapi.auth.exception.InvalidCredentialsException;
import com.clasificacion.platformapi.auth.exception.InvalidTokenException;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public class AuthErrorHandler {
    @ExceptionHandler(EmailAlreadyExistsException.class)
    public ResponseEntity<Map<String, String>> handleEmailConflict(EmailAlreadyExistsException exc) {
        return ResponseEntity.status(HttpStatus.CONFLICT).body(Map.of("detail", exc.getMessage()));
    }

    @ExceptionHandler({InvalidCredentialsException.class, InvalidTokenException.class})
    public ResponseEntity<Map<String, String>> handleUnauthorized(RuntimeException exc) {
        return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body(Map.of("detail", exc.getMessage()));
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
