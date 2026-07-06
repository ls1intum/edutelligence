package de.tum.cit.aet.logos.logoswebservice.websocket;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.socket.config.annotation.EnableWebSocket;
import org.springframework.web.socket.config.annotation.WebSocketConfigurer;
import org.springframework.web.socket.config.annotation.WebSocketHandlerRegistry;

@Configuration
@EnableWebSocket
public class WebSocketConfig implements WebSocketConfigurer {

    private final StatsWebSocketHandler v1Handler;
    private final StatsV2WebSocketHandler v2Handler;
    private final WebSocketAuthInterceptor authInterceptor;

    public WebSocketConfig(StatsWebSocketHandler v1Handler,
                           StatsV2WebSocketHandler v2Handler,
                           WebSocketAuthInterceptor authInterceptor) {
        this.v1Handler = v1Handler;
        this.v2Handler = v2Handler;
        this.authInterceptor = authInterceptor;
    }

    @Override
    public void registerWebSocketHandlers(WebSocketHandlerRegistry registry) {
        registry.addHandler(v1Handler, "/ws/stats")
                .addInterceptors(authInterceptor)
                .setAllowedOrigins("*");

        registry.addHandler(v2Handler, "/ws/stats/v2")
                .addInterceptors(authInterceptor)
                .setAllowedOrigins("*");
    }
}
