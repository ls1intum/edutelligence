package de.tum.cit.aet.logos.logoswebservice.websocket;

import org.springframework.context.annotation.Configuration;
import org.springframework.web.socket.config.annotation.EnableWebSocket;
import org.springframework.web.socket.config.annotation.WebSocketConfigurer;
import org.springframework.web.socket.config.annotation.WebSocketHandlerRegistry;

import de.tum.cit.aet.logos.logoswebservice.notifications.realtime.NotificationHandshakeInterceptor;
import de.tum.cit.aet.logos.logoswebservice.notifications.realtime.NotificationSocketHandler;

@Configuration
@EnableWebSocket
public class WebSocketConfig implements WebSocketConfigurer {

    private final StatsWebSocketHandler v1Handler;
    private final StatsV2WebSocketHandler v2Handler;
    private final WebSocketAuthInterceptor authInterceptor;
    private final NotificationSocketHandler notificationHandler;
    private final NotificationHandshakeInterceptor notificationInterceptor;

    public WebSocketConfig(StatsWebSocketHandler v1Handler,
                           StatsV2WebSocketHandler v2Handler,
                           WebSocketAuthInterceptor authInterceptor,
                           NotificationSocketHandler notificationHandler,
                           NotificationHandshakeInterceptor notificationInterceptor) {
        this.v1Handler = v1Handler;
        this.v2Handler = v2Handler;
        this.authInterceptor = authInterceptor;
        this.notificationHandler = notificationHandler;
        this.notificationInterceptor = notificationInterceptor;
    }

    @Override
    public void registerWebSocketHandlers(WebSocketHandlerRegistry registry) {
        registry.addHandler(v1Handler, "/ws/stats")
                .addInterceptors(authInterceptor)
                .setAllowedOrigins("*");

        registry.addHandler(v2Handler, "/ws/stats/v2")
                .addInterceptors(authInterceptor)
                .setAllowedOrigins("*");

        // Open to every active user; each socket only gets its own notifications.
        registry.addHandler(notificationHandler, "/ws/notifications")
                .addInterceptors(notificationInterceptor)
                .setAllowedOrigins("*");
    }
}
