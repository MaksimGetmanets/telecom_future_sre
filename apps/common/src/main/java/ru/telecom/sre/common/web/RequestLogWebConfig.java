package ru.telecom.sre.common.web;

import org.springframework.context.annotation.Configuration;
import org.springframework.core.Ordered;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * Лог запросов к бизнес-ручкам и ручкам сбоев. /actuator не логируем: пробы и скрейп дали бы шум.
 * Interceptor идёт первым, поэтому запись появляется и тогда, когда FaultInterceptor прервал запрос (500).
 */
@Configuration
public class RequestLogWebConfig implements WebMvcConfigurer {

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(new RequestLogInterceptor())
                .addPathPatterns("/orders", "/orders/**", "/slow", "/fail", "/leak", "/fault")
                .order(Ordered.HIGHEST_PRECEDENCE);
    }
}
