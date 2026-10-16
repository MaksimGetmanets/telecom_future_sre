package ru.telecom.sre.common.fault;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
@ConditionalOnProperty(name = "faults.enabled", havingValue = "true", matchIfMissing = true)
public class FaultWebConfig implements WebMvcConfigurer {

    private final FaultState state;

    public FaultWebConfig(FaultState state) {
        this.state = state;
    }

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(new FaultInterceptor(state))
                .addPathPatterns("/orders", "/orders/**");
    }
}
