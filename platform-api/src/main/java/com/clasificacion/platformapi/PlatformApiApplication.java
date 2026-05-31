package com.clasificacion.platformapi;

import com.clasificacion.platformapi.ai.config.AiEngineProperties;
import com.clasificacion.platformapi.auth.config.AuthProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;

@SpringBootApplication
@EnableConfigurationProperties({AuthProperties.class, AiEngineProperties.class})
public class PlatformApiApplication {

	public static void main(String[] args) {
		SpringApplication.run(PlatformApiApplication.class, args);
	}

}
