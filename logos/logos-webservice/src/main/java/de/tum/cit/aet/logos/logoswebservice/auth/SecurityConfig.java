package de.tum.cit.aet.logos.logoswebservice.auth;

import java.io.IOException;
import java.util.ArrayList;
import java.util.List;

import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.security.config.Customizer;
import org.springframework.security.config.annotation.method.configuration.EnableMethodSecurity;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.oauth2.core.DelegatingOAuth2TokenValidator;
import org.springframework.security.oauth2.core.OAuth2Error;
import org.springframework.security.oauth2.core.OAuth2TokenValidator;
import org.springframework.security.oauth2.core.OAuth2TokenValidatorResult;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.jwt.JwtValidators;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;
import org.springframework.security.oauth2.server.resource.web.BearerTokenResolver;
import org.springframework.security.oauth2.server.resource.web.DefaultBearerTokenResolver;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.web.cors.CorsConfiguration;
import org.springframework.web.cors.CorsConfigurationSource;
import org.springframework.web.cors.UrlBasedCorsConfigurationSource;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

@Configuration
@EnableMethodSecurity
public class SecurityConfig {

    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http,
            @Qualifier("logosCorsConfigurationSource") CorsConfigurationSource corsSource) throws Exception {
        http
            .cors(cors -> cors.configurationSource(corsSource))
            .csrf(csrf -> csrf.disable())
            .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            .authorizeHttpRequests(auth -> auth
                .requestMatchers(HttpMethod.OPTIONS, "/**").permitAll()
                .requestMatchers("/error").permitAll()
                .anyRequest().authenticated())
            .oauth2ResourceServer(rs -> rs
                .bearerTokenResolver(new LogosBearerTokenResolver())
                .jwt(Customizer.withDefaults())
                .authenticationEntryPoint(SecurityConfig::writeUnauthorized))
            .exceptionHandling(ex -> ex
                .authenticationEntryPoint(SecurityConfig::writeUnauthorized)
                .accessDeniedHandler((request, response, e) -> {
                    response.setStatus(403);
                    response.setContentType("application/json");
                    response.getWriter().write("{\"detail\":\"Forbidden\"}");
                }));
        return http.build();
    }

    @Bean("logosCorsConfigurationSource")
    public CorsConfigurationSource logosCorsConfigurationSource(
            @Value("${logos.cors.allowed-origins:}") String allowedOrigins) {
        CorsConfiguration cfg = new CorsConfiguration();
        // Default: no allowed origins. Browsers' same-origin policy applies — set
        // `logos.cors.allowed-origins` explicitly (comma-separated) for any
        // cross-origin browser client. The pattern form is permitted so that
        // dev set-ups can use `*`, but credentialed `*` is rejected by Spring
        // by design — use specific origins in production.
        boolean credentialsSafe = true;
        for (String origin : allowedOrigins.split(",")) {
            String o = origin.strip();
            if (o.isEmpty()) continue;
            if (o.contains("*")) {
                cfg.addAllowedOriginPattern(o);
                credentialsSafe = false;
            } else {
                cfg.addAllowedOrigin(o);
            }
        }
        cfg.setAllowedMethods(List.of("GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"));
        cfg.setAllowedHeaders(List.of("Authorization", "Content-Type", "logos_key", "logos-key"));
        cfg.setAllowCredentials(credentialsSafe);
        UrlBasedCorsConfigurationSource source = new UrlBasedCorsConfigurationSource();
        source.registerCorsConfiguration("/**", cfg);
        return source;
    }

    @Bean
    public JwtDecoder jwtDecoder(
            @Value("${spring.security.oauth2.resourceserver.jwt.jwk-set-uri}") String jwkSetUri,
            @Value("${spring.security.oauth2.resourceserver.jwt.issuer-uri}") String issuerUri,
            KeycloakProperties props) {
        NimbusJwtDecoder decoder = NimbusJwtDecoder.withJwkSetUri(jwkSetUri).build();
        List<OAuth2TokenValidator<Jwt>> validators = new ArrayList<>();
        validators.add(JwtValidators.createDefaultWithIssuer(issuerUri));
        if (props.audience() != null && !props.audience().isBlank()) {
            validators.add(new AudienceValidator(props.audience()));
        }
        decoder.setJwtValidator(new DelegatingOAuth2TokenValidator<>(validators));
        return decoder;
    }

    static class AudienceValidator implements OAuth2TokenValidator<Jwt> {

        private final String expected;

        AudienceValidator(String expected) {
            this.expected = expected;
        }

        @Override
        public OAuth2TokenValidatorResult validate(Jwt jwt) {
            List<String> aud = jwt.getAudience();
            if ((aud != null && aud.contains(expected)) || expected.equals(jwt.getClaimAsString("azp"))) {
                return OAuth2TokenValidatorResult.success();
            }
            return OAuth2TokenValidatorResult.failure(new OAuth2Error(
                "invalid_token", "Required audience '" + expected + "' is missing", null));
        }
    }

    private static void writeUnauthorized(HttpServletRequest request, HttpServletResponse response,
                                          org.springframework.security.core.AuthenticationException e)
            throws IOException {
        response.setStatus(401);
        response.setContentType("application/json");
        response.getWriter().write("{\"detail\":\"Invalid or missing bearer token\"}");
    }

    static class LogosBearerTokenResolver implements BearerTokenResolver {

        private final DefaultBearerTokenResolver defaultResolver = new DefaultBearerTokenResolver();

        @Override
        public String resolve(HttpServletRequest request) {
            String token = defaultResolver.resolve(request);
            if (token != null) return token;
            token = request.getHeader("logos_key");
            if (token != null) return token.strip();
            token = request.getHeader("logos-key");
            if (token != null) return token.strip();
            if (request.getRequestURI().startsWith("/ws/")) {
                String fromKey = singleNonBlank(request.getParameterValues("key"));
                String fromToken = singleNonBlank(request.getParameterValues("token"));
                if (fromKey != null && fromToken != null) return null;
                return fromKey != null ? fromKey : fromToken;
            }
            return null;
        }

        private static String singleNonBlank(String[] values) {
            if (values == null || values.length != 1) return null;
            String v = values[0];
            if (v == null) return null;
            v = v.strip();
            return v.isEmpty() ? null : v;
        }
    }
}
