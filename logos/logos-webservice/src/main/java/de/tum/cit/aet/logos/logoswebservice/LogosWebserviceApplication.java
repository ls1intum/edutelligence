package de.tum.cit.aet.logos.logoswebservice;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.ConfigurationPropertiesScan;
import org.springframework.scheduling.annotation.EnableAsync;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@ConfigurationPropertiesScan
@EnableScheduling
@EnableAsync
public class LogosWebserviceApplication {

    public static void main(String[] args) {
        SpringApplication.run(LogosWebserviceApplication.class, args);
    }

}
