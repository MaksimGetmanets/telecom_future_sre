package ru.telecom.sre.gateway;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestClient;

@Configuration
public class RestClientConfig {

    @Bean
    public RestClient ordersClient(RestClient.Builder builder, @Value("${orders.url}") String ordersUrl) {
        return builder.baseUrl(ordersUrl).build();
    }
}
