package ru.telecom.sre.gateway;

import java.util.function.Supplier;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientResponseException;

/** Пропускает запросы к заказам в сервис orders и сохраняет статус ответа. */
@RestController
@RequestMapping("/orders")
public class OrdersProxyController {

    private static final Logger log = LoggerFactory.getLogger(OrdersProxyController.class);

    private final RestClient orders;

    public OrdersProxyController(RestClient ordersClient) {
        this.orders = ordersClient;
    }

    @GetMapping
    public ResponseEntity<String> list() {
        return call(() -> orders.get().uri("/orders").retrieve().toEntity(String.class));
    }

    @GetMapping("/{id}")
    public ResponseEntity<String> get(@PathVariable long id) {
        return call(() -> orders.get().uri("/orders/{id}", id).retrieve().toEntity(String.class));
    }

    @PostMapping
    public ResponseEntity<String> create(@RequestBody String body) {
        return call(() -> orders.post()
                .uri("/orders")
                .contentType(MediaType.APPLICATION_JSON)
                .body(body)
                .retrieve()
                .toEntity(String.class));
    }

    private ResponseEntity<String> call(Supplier<ResponseEntity<String>> request) {
        try {
            ResponseEntity<String> response = request.get();
            return ResponseEntity.status(response.getStatusCode())
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(response.getBody());
        } catch (RestClientResponseException e) {
            log.warn("orders responded with status {}", e.getStatusCode().value());
            return ResponseEntity.status(e.getStatusCode())
                    .contentType(MediaType.APPLICATION_JSON)
                    .body(e.getResponseBodyAsString());
        } catch (ResourceAccessException e) {
            log.error("orders is unreachable: {}", e.getMessage());
            return ResponseEntity.status(HttpStatus.BAD_GATEWAY)
                    .contentType(MediaType.APPLICATION_JSON)
                    .body("{\"error\":\"orders unavailable\"}");
        }
    }
}
