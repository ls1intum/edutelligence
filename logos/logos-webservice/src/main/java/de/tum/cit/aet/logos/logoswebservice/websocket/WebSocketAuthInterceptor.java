package de.tum.cit.aet.logos.logoswebservice.websocket;

import java.util.Map;

import org.springframework.http.server.ServerHttpRequest;
import org.springframework.http.server.ServerHttpResponse;
import org.springframework.http.server.ServletServerHttpRequest;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.WebSocketHandler;
import org.springframework.web.socket.server.HandshakeInterceptor;

import de.tum.cit.aet.logos.logoswebservice.identity.repository.ApiKeyRepository;

@Component
public class WebSocketAuthInterceptor implements HandshakeInterceptor {

    private final ApiKeyRepository apiKeyRepository;

    public WebSocketAuthInterceptor(ApiKeyRepository apiKeyRepository) {
        this.apiKeyRepository = apiKeyRepository;
    }

    @Override
    public boolean beforeHandshake(ServerHttpRequest request, ServerHttpResponse response,
                                   WebSocketHandler wsHandler, Map<String, Object> attributes) {
        if (!(request instanceof ServletServerHttpRequest servletRequest)) return false;
        String key = servletRequest.getServletRequest().getParameter("key");
        if (key == null || key.isBlank()) return false;
        boolean valid = apiKeyRepository.findByKeyValueAndIsActiveTrue(key).isPresent();
        if (valid) attributes.put("logosKey", key);
        return valid;
    }

    @Override
    public void afterHandshake(ServerHttpRequest request, ServerHttpResponse response,
                               WebSocketHandler wsHandler, Exception exception) {}
}
