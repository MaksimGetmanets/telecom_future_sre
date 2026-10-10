package ru.telecom.sre.orders;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

// scanBasePackages захватывает и общий модуль ru.telecom.sre.common
@SpringBootApplication(scanBasePackages = "ru.telecom.sre")
public class OrdersApplication {

    public static void main(String[] args) {
        SpringApplication.run(OrdersApplication.class, args);
    }
}
