package de.tum.cit.aet.logos.logoswebservice.common;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Primary;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestTemplate;

@Configuration
public class RestTemplateConfig {

    /** Name of the template for calls that legitimately take minutes. */
    public static final String LONG_RUNNING = "longRunningRestTemplate";

    @Bean
    @Primary
    public RestTemplate restTemplate() {
        return build(5_000);
    }

    /**
     * Same configuration as {@link #restTemplate()} but with a read timeout that
     * survives a worker loading a model (see the {@code add_lane} admin call).
     *
     * <p>Defined as a bean rather than hand-built at the call site so that any
     * future converter, interceptor or error-handler added to this class applies
     * to both templates instead of silently skipping the long-running one.
     */
    @Bean(LONG_RUNNING)
    public RestTemplate longRunningRestTemplate() {
        return build(185_000);
    }

    private static RestTemplate build(int readTimeoutMs) {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(3_000);
        factory.setReadTimeout(readTimeoutMs);
        return new RestTemplate(factory);
    }
}
