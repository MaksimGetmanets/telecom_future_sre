package ru.telecom.sre.common.web;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.web.servlet.HandlerInterceptor;

/**
 * Пишет одну строку лога на каждый бизнес-запрос. Выполняется внутри спана OpenTelemetry,
 * поэтому в JSON-лог попадают trace_id и span_id: по ним из лога можно открыть трейс.
 * Уровень зависит от статуса: 5xx это ERROR, 4xx это WARN, остальное INFO.
 */
public class RequestLogInterceptor implements HandlerInterceptor {

    private static final Logger log = LoggerFactory.getLogger("http.access");
    private static final String START = RequestLogInterceptor.class.getName() + ".start";

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
        request.setAttribute(START, System.nanoTime());
        return true;
    }

    @Override
    public void afterCompletion(HttpServletRequest request, HttpServletResponse response, Object handler,
                                Exception ex) {
        Object start = request.getAttribute(START);
        long ms = start == null ? -1 : (System.nanoTime() - (Long) start) / 1_000_000;
        int status = response.getStatus();
        if (ex != null || status >= 500) {
            log.error("{} {} status={} duration_ms={}", request.getMethod(), request.getRequestURI(), status, ms, ex);
        } else if (status >= 400) {
            log.warn("{} {} status={} duration_ms={}", request.getMethod(), request.getRequestURI(), status, ms);
        } else {
            log.info("{} {} status={} duration_ms={}", request.getMethod(), request.getRequestURI(), status, ms);
        }
    }
}
