package com.clasificacion.platformapi.auth.exception;

public class InvalidCredentialsException extends AuthException {
    public InvalidCredentialsException() {
        super("Credenciales invalidas");
    }

    public InvalidCredentialsException(String message) {
        super(message);
    }
}
