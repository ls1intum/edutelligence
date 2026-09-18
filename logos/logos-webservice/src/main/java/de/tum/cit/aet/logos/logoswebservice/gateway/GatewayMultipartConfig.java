package de.tum.cit.aet.logos.logoswebservice.gateway;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.multipart.MultipartException;
import org.springframework.web.multipart.MultipartHttpServletRequest;
import org.springframework.web.multipart.MultipartResolver;
import org.springframework.web.multipart.support.StandardServletMultipartResolver;

import jakarta.servlet.http.HttpServletRequest;

/**
 * Multipart resolver that leaves inference-gateway paths alone so the
 * controller can reverse-proxy the raw body (Boot's default eager resolver
 * would otherwise consume the stream before {@code readAllBytes()}).
 *
 * <p>Management uploads ({@code /users/import}, batch files, …) still go
 * through the standard resolver. Replaces Boot's auto-configured
 * {@code multipartResolver} bean.
 */
@Configuration
public class GatewayMultipartConfig {

    @Bean(name = "multipartResolver")
    MultipartResolver multipartResolver() {
        StandardServletMultipartResolver delegate = new StandardServletMultipartResolver();
        return new MultipartResolver() {
            @Override
            public boolean isMultipart(HttpServletRequest request) {
                if (isGatewayPath(request)) {
                    return false;
                }
                return delegate.isMultipart(request);
            }

            @Override
            public MultipartHttpServletRequest resolveMultipart(HttpServletRequest request)
                    throws MultipartException {
                return delegate.resolveMultipart(request);
            }

            @Override
            public void cleanupMultipart(MultipartHttpServletRequest request) {
                delegate.cleanupMultipart(request);
            }
        };
    }

    static boolean isGatewayPath(HttpServletRequest request) {
        String path = request.getRequestURI();
        String context = request.getContextPath();
        if (context != null && !context.isEmpty() && path.startsWith(context)) {
            path = path.substring(context.length());
        }
        return path.equals("/v1") || path.startsWith("/v1/")
            || path.equals("/openai") || path.startsWith("/openai/")
            || path.equals("/jobs") || path.startsWith("/jobs/");
    }
}
