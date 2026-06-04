package de.tum.cit.aet.logos.logoswebservice.auth;

import de.tum.cit.aet.logos.logoswebservice.identity.entity.ApiKey;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.ApiKeyRepository;
import de.tum.cit.aet.logos.logoswebservice.identity.repository.UserRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.Mockito;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;

class AuthInterceptorTest {

    ApiKeyRepository apiKeyRepository;
    UserRepository userRepository;
    AuthInterceptor interceptor;

    @BeforeEach
    void setUp() {
        apiKeyRepository = Mockito.mock(ApiKeyRepository.class);
        userRepository = Mockito.mock(UserRepository.class);
        interceptor = new AuthInterceptor(apiKeyRepository, userRepository);
    }

    @Test
    void rejectsRequestWithNoKey() throws Exception {
        var request = new MockHttpServletRequest("GET", "/me");
        var response = new MockHttpServletResponse();

        boolean proceed = interceptor.preHandle(request, response, new Object());

        assertThat(proceed).isFalse();
        assertThat(response.getStatus()).isEqualTo(401);
    }

    @Test
    void rejectsRequestWithInactiveKey() throws Exception {
        Mockito.when(apiKeyRepository.findByKeyValueAndIsActiveTrue("bad-key"))
               .thenReturn(Optional.empty());

        var request = new MockHttpServletRequest("GET", "/me");
        request.addHeader("logos-key", "bad-key");
        var response = new MockHttpServletResponse();

        boolean proceed = interceptor.preHandle(request, response, new Object());

        assertThat(proceed).isFalse();
        assertThat(response.getStatus()).isEqualTo(401);
    }

    @Test
    void acceptsValidLogosKey() throws Exception {
        ApiKey key = validApiKey("test-key", null);
        Mockito.when(apiKeyRepository.findByKeyValueAndIsActiveTrue("test-key"))
               .thenReturn(Optional.of(key));

        var request = new MockHttpServletRequest("GET", "/me");
        request.addHeader("logos-key", "test-key");
        var response = new MockHttpServletResponse();

        boolean proceed = interceptor.preHandle(request, response, new Object());

        assertThat(proceed).isTrue();
        AuthContext ctx = (AuthContext) request.getAttribute("authContext");
        assertThat(ctx).isNotNull();
        assertThat(ctx.keyValue()).isEqualTo("test-key");
    }

    @Test
    void acceptsBearerToken() throws Exception {
        ApiKey key = validApiKey("bearer-key", null);
        Mockito.when(apiKeyRepository.findByKeyValueAndIsActiveTrue("bearer-key"))
               .thenReturn(Optional.of(key));

        var request = new MockHttpServletRequest("GET", "/me");
        request.addHeader("Authorization", "Bearer bearer-key");
        var response = new MockHttpServletResponse();

        boolean proceed = interceptor.preHandle(request, response, new Object());

        assertThat(proceed).isTrue();
    }

    private ApiKey validApiKey(String value, Integer userId) {
        ApiKey k = new ApiKey();
        k.setKeyValue(value);
        k.setIsActive(true);
        k.setUserId(userId);
        k.setName("test");
        k.setKeyType("developer");
        return k;
    }
}