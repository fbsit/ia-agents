package com.clasificacion.platformapi.auth.exception;

public class EmailAlreadyExistsException extends AuthException {
    public EmailAlreadyExistsException() {
        super("El email ya esta registrado");
    }
}
