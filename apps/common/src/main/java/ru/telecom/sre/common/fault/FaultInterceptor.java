package ru.telecom.sre.common.fault;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

import org.springframework.http.MediaType;
import org.springframework.web.servlet.HandlerInterceptor;

/**
 * Применяет внедрённую задержку и долю ошибок к бизнес-ручкам.
 * Работает как interceptor (а не как фильтр), чтобы метрика http_server_requests
 * сохраняла корректный тег uri.
 */
public class FaultInterceptor implements HandlerInterceptor {

    private final FaultState state;

    public FaultInterceptor(FaultState state) {
        this.state = state;
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler)
            throws Exception {
        long delay = state.delayMs();
        if (delay > 0) {
            try {
                Thread.sleep(delay);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }
        if (state.shouldFail()) {
            response.setStatus(HttpServletResponse.SC_INTERNAL_SERVER_ERROR);
            response.setContentType(MediaType.APPLICATION_JSON_VALUE);
            response.getWriter().write("{\"error\":\"injected fault\"}");
            return false;
        }
        return true;
    }
}
