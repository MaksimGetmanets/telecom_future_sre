package ru.telecom.sre.common.fault;

import java.util.Map;
import java.util.concurrent.ThreadLocalRandom;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestMethod;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/**
 * Ручки для имитации сбоев (хаос-сценарии и демо).
 * Отключаются свойством faults.enabled=false.
 */
@RestController
@ConditionalOnProperty(name = "faults.enabled", havingValue = "true", matchIfMissing = true)
public class FaultController {

    private final FaultState state;

    public FaultController(FaultState state) {
        this.state = state;
    }

    /** Отвечает с задержкой: /slow?ms=1500 */
    @GetMapping("/slow")
    public Map<String, Object> slow(@RequestParam(defaultValue = "1000") long ms) throws InterruptedException {
        long sleep = Math.max(0L, Math.min(ms, 30_000L));
        Thread.sleep(sleep);
        return Map.of("sleptMs", sleep);
    }

    /** Падает с HTTP 500 с вероятностью p: /fail?p=0.3 */
    @GetMapping("/fail")
    public ResponseEntity<Map<String, Object>> fail(@RequestParam(defaultValue = "1.0") double p) {
        double prob = Math.max(0.0, Math.min(p, 1.0));
        if (ThreadLocalRandom.current().nextDouble() < prob) {
            return ResponseEntity.status(500).body(Map.of("error", "injected failure", "p", prob));
        }
        return ResponseEntity.ok(Map.of("ok", true, "p", prob));
    }

    /** Утечка памяти: /leak?mb=50 добавляет 50 МБ в кучу, которые не освобождаются. */
    @RequestMapping(path = "/leak", method = {RequestMethod.GET, RequestMethod.POST})
    public Map<String, Object> leak(@RequestParam(defaultValue = "50") int mb) {
        state.leak(Math.max(0, Math.min(mb, 512)));
        return Map.of("leakedMb", state.leakedMb());
    }

    @DeleteMapping("/leak")
    public Map<String, Object> clearLeak() {
        state.clearLeak();
        return Map.of("leakedMb", state.leakedMb());
    }

    /** Текущее состояние внедрённых сбоев. */
    @GetMapping("/fault")
    public Map<String, Object> getFault() {
        return describe();
    }

    /**
     * Постоянный сбой на бизнес-ручках (/orders): доля ошибок и задержка.
     * Пример: POST /fault?errorRate=0.5&delayMs=300. Перезапуск пода сбрасывает.
     */
    @PostMapping("/fault")
    public Map<String, Object> setFault(@RequestParam(defaultValue = "0") double errorRate,
                                        @RequestParam(defaultValue = "0") long delayMs) {
        state.set(errorRate, delayMs);
        return describe();
    }

    @DeleteMapping("/fault")
    public Map<String, Object> resetFault() {
        state.reset();
        return describe();
    }

    private Map<String, Object> describe() {
        return Map.of(
                "errorRate", state.errorRate(),
                "delayMs", state.delayMs(),
                "leakedMb", state.leakedMb());
    }
}
