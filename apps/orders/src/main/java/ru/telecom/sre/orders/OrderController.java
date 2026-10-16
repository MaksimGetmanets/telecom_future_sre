package ru.telecom.sre.orders;

import java.util.List;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/orders")
public class OrderController {

    private static final Logger log = LoggerFactory.getLogger(OrderController.class);

    private final OrderRepository repository;

    public OrderController(OrderRepository repository) {
        this.repository = repository;
    }

    public record CreateOrderRequest(String item, int quantity) {
    }

    /** Последние 50 заказов, новые первыми. */
    @GetMapping
    public List<Order> list() {
        return repository.findAll(PageRequest.of(0, 50, Sort.by(Sort.Direction.DESC, "id"))).getContent();
    }

    @GetMapping("/{id}")
    public Order get(@PathVariable long id) {
        return repository.findById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "order not found"));
    }

    @PostMapping
    public ResponseEntity<Order> create(@RequestBody CreateOrderRequest request) {
        if (request.item() == null || request.item().isBlank() || request.quantity() < 1) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "item is required and quantity must be >= 1");
        }
        Order saved = repository.save(new Order(request.item().trim(), request.quantity()));
        log.info("order created id={} item={} quantity={}", saved.getId(), saved.getItem(), saved.getQuantity());
        return ResponseEntity.status(HttpStatus.CREATED).body(saved);
    }
}
