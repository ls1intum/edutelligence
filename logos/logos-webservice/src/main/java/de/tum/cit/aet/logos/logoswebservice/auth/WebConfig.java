package de.tum.cit.aet.logos.logoswebservice.auth;

import java.util.concurrent.Executor;

import org.springframework.beans.factory.ObjectProvider;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.task.AsyncTaskExecutor;
import org.springframework.core.task.support.TaskExecutorAdapter;
import org.springframework.web.client.RestClient;
import org.springframework.web.servlet.config.annotation.AsyncSupportConfigurer;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
public class WebConfig implements WebMvcConfigurer {

    private final JwtAuthInterceptor jwtAuthInterceptor;
    private final ObjectProvider<Executor> applicationTaskExecutor;

    public WebConfig(
            JwtAuthInterceptor jwtAuthInterceptor,
            @Qualifier("applicationTaskExecutor") ObjectProvider<Executor> applicationTaskExecutor) {
        this.jwtAuthInterceptor = jwtAuthInterceptor;
        this.applicationTaskExecutor = applicationTaskExecutor;
    }

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(jwtAuthInterceptor)
            // get_model_health and models_discovered authenticate API key /
            // internal secret in their controllers, not a JWT. The inference
            // gateway (/v1, /openai, /jobs) likewise uses Logos API keys.
            .excludePathPatterns(
                "/error", "/info", "/ws/**",
                "/logosdb/get_model_health", "/internal/models_discovered",
                "/v1", "/v1/**", "/openai", "/openai/**", "/jobs", "/jobs/**");
    }

    @Override
    public void configureAsyncSupport(AsyncSupportConfigurer configurer) {
        // StreamingResponseBody (inference gateway) runs on this pool — keep it
        // bounded via spring.task.execution.pool.* in application.properties.
        Executor executor = applicationTaskExecutor.getIfAvailable();
        if (executor == null) {
            return;
        }
        AsyncTaskExecutor async = executor instanceof AsyncTaskExecutor ate
            ? ate
            : new TaskExecutorAdapter(executor);
        configurer.setTaskExecutor(async);
    }

    @Bean
    public RestClient.Builder restClientBuilder() {
        return RestClient.builder();
    }
}
