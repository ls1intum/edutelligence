package de.tum.cit.aet.logos.logoswebservice.common;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestTemplate;

@Configuration
public class RestTemplateConfig {

    @Bean
    public RestTemplate restTemplate() {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(3_000);
        factory.setReadTimeout(5_000);
        return new RestTemplate(factory);
    }

    /**
     * Template for the worker admin endpoints (lane add/sleep/wake/delete).
     *
     * A sleep with mode="wait" first drains the lane's in-flight requests and
     * a wake can take up to the orchestrator's 120 s command budget, so the
     * shared 5 s read timeout above would cut them off exactly when the worker
     * is doing the real work.
     */
    @Bean
    public RestTemplate workerAdminRestTemplate() {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(3_000);
        factory.setReadTimeout(130_000);
        return new RestTemplate(factory);
    }
}
