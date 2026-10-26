package de.tum.cit.aet.logos.logoswebservice.gateway;

import java.util.concurrent.Callable;

import org.springframework.web.context.request.NativeWebRequest;
import org.springframework.web.context.request.RequestAttributes;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.async.CallableProcessingInterceptor;

/**
 * Closes the upstream reader of a cloud relay when its request ends.
 *
 * <p>The forwarder starts reading the upstream before the relay task runs.
 * When MVC rejects that task, times it out, or the request fails before the
 * task ran, nothing else would stop the reader. Spring calls
 * {@link #afterCompletion} for every async request once it is over, however
 * it ended; for a relay that ran to the end the pump is already closed and
 * closing it again does nothing.
 */
public final class GatewayRelayCleanup implements CallableProcessingInterceptor {

    static final String ATTRIBUTE = GatewayRelayCleanup.class.getName() + ".pump";

    /** Registers {@code pump} with the current request, if there is one. */
    static void closeWhenRequestEnds(GatewayCloudForwarder.UpstreamPump pump) {
        RequestAttributes attributes = RequestContextHolder.getRequestAttributes();
        if (attributes != null) {
            attributes.setAttribute(ATTRIBUTE, pump, RequestAttributes.SCOPE_REQUEST);
        }
    }

    @Override
    public <T> void afterCompletion(NativeWebRequest request, Callable<T> task) {
        if (request.getAttribute(ATTRIBUTE, RequestAttributes.SCOPE_REQUEST)
                instanceof GatewayCloudForwarder.UpstreamPump pump) {
            pump.close();
        }
    }
}
