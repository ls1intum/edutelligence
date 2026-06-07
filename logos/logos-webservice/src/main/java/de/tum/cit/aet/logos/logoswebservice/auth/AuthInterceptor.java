package de.tum.cit.aet.logos.logoswebservice.auth;

import java.util.Optional;

import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKey;
import de.tum.cit.aet.logos.logoswebservice.identity.entity.User;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.ApiKeyRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.UserRepository;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

@Component
public class AuthInterceptor implements HandlerInterceptor {

    private final ApiKeyRepository apiKeyRepository;
    private final UserRepository userRepository;

    public AuthInterceptor(ApiKeyRepository apiKeyRepository, UserRepository userRepository) {
        this.apiKeyRepository = apiKeyRepository;
        this.userRepository = userRepository;
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler)
            throws Exception {
        String key = resolveKey(request);
        if (key == null) {
            response.sendError(401, "Missing logos key");
            return false;
        }
        Optional<ApiKey> apiKey = apiKeyRepository.findByKeyValueAndIsActiveTrue(key);
        if (apiKey.isEmpty()) {
            response.sendError(401, "Invalid or inactive logos key");
            return false;
        }
        ApiKey k = apiKey.get();
        String role = null;
        if (k.getUserId() != null) {
            role = userRepository.findById(k.getUserId()).map(User::getRole).orElse(null);
        }
        request.setAttribute("authContext", new AuthContext(
            key, k.getId(), k.getName(), k.getKeyType(), k.getTeamId(), k.getUserId(), role
        ));
        return true;
    }

    private String resolveKey(HttpServletRequest request) {
        String key = request.getHeader("logos_key");
        if (key != null) return key;
        key = request.getHeader("logos-key");
        if (key != null) return key;
        String auth = request.getHeader("Authorization");
        if (auth == null) auth = request.getHeader("authorization");
        if (auth != null) {
            String trimmed = auth.strip();
            if (trimmed.toLowerCase().startsWith("bearer ")) return trimmed.substring(7).strip();
            return trimmed;
        }
        return null;
    }
}
