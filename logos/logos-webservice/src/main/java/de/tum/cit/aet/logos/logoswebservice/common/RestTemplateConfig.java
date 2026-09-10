package de.tum.cit.aet.logos.logoswebservice.common;

import java.io.IOException;
import java.net.HttpURLConnection;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Primary;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestTemplate;

@Configuration
public class RestTemplateConfig {

    // @Primary: the worker admin client qualifies its way to the long-timeout
    // bean below; every other RestTemplate injection resolves to this one
    // explicitly instead of by parameter-name fallback.
    @Primary
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

    /**
     * Template for the batch proxy, which sends the caller's own API key.
     *
     * The key travels in a custom header (logos_key), and a redirect would
     * carry it along: the connection resends the request headers onto the
     * redirected request. The orchestrator answers every batch call
     * directly, so redirects have no legitimate purpose here and are
     * refused at the connection level — the 3xx comes back as the response,
     * and the service turns it into an error instead of following it into
     * wherever it points.
     */
    @Bean
    public RestTemplate batchRestTemplate() {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory() {
            @Override
            protected void prepareConnection(HttpURLConnection connection, String httpMethod) throws IOException {
                super.prepareConnection(connection, httpMethod);
                connection.setInstanceFollowRedirects(false);
            }
        };
        factory.setConnectTimeout(3_000);
        factory.setReadTimeout(5_000);
        return new RestTemplate(factory);
    }
}
