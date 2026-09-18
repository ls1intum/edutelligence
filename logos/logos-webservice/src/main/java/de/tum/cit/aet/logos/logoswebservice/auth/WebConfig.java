package de.tum.cit.aet.logos.logoswebservice.auth;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestClient;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

@Configuration
public class WebConfig implements WebMvcConfigurer {

    private final JwtAuthInterceptor jwtAuthInterceptor;

    public WebConfig(JwtAuthInterceptor jwtAuthInterceptor) {
        this.jwtAuthInterceptor = jwtAuthInterceptor;
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

    @Bean
    public RestClient.Builder restClientBuilder() {
        return RestClient.builder();
    }
}
