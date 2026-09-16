package com.clasificacion.platformapi.config;

import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Pool compartido para las tareas de poll-y-comparar de los streams SSE
 * (conversaciones/mensajes en vivo). Un solo pool para todos los emitters
 * conectados, no uno por conexion.
 */
@Configuration
public class SseSchedulerConfig {
    @Bean
    public ScheduledExecutorService conversationStreamScheduler() {
        return Executors.newScheduledThreadPool(4);
    }
}
