package ru.telecom.sre.common.fault;

import java.util.Arrays;
import java.util.List;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.ThreadLocalRandom;

import org.springframework.stereotype.Component;

/**
 * Состояние внедрённых сбоев. Хранится только в памяти пода:
 * перезапуск пода сбрасывает всё, поэтому "рестарт" реально лечит эти сбои.
 */
@Component
public class FaultState {

    private static final int CHUNK_BYTES = 1024 * 1024; // 1 МБ

    private volatile double errorRate = 0.0;
    private volatile long delayMs = 0;
    private final List<byte[]> leaked = new CopyOnWriteArrayList<>();

    public void set(double errorRate, long delayMs) {
        this.errorRate = Math.max(0.0, Math.min(errorRate, 1.0));
        this.delayMs = Math.max(0L, Math.min(delayMs, 60_000L));
    }

    public void reset() {
        this.errorRate = 0.0;
        this.delayMs = 0;
    }

    public double errorRate() {
        return errorRate;
    }

    public long delayMs() {
        return delayMs;
    }

    public boolean shouldFail() {
        double p = errorRate;
        return p > 0.0 && ThreadLocalRandom.current().nextDouble() < p;
    }

    /** Удерживает в куче mb мегабайт, которые GC не сможет освободить. */
    public void leak(int mb) {
        for (int i = 0; i < mb; i++) {
            byte[] chunk = new byte[CHUNK_BYTES];
            Arrays.fill(chunk, (byte) 1);
            leaked.add(chunk);
        }
    }

    public void clearLeak() {
        leaked.clear();
    }

    public int leakedMb() {
        return leaked.size();
    }
}
