package ru.telecom.sre.gateway;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

// scanBasePackages захватывает и общий модуль ru.telecom.sre.common
@SpringBootApplication(scanBasePackages = "ru.telecom.sre")
public class GatewayApplication {

    public static void main(String[] args) {
        SpringApplication.run(GatewayApplication.class, args);
    }
}
