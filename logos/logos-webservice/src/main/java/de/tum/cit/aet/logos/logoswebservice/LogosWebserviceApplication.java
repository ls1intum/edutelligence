package de.tum.cit.aet.logos.logoswebservice;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

@SpringBootApplication
@EnableScheduling
public class LogosWebserviceApplication {

    public static void main(String[] args) {
        SpringApplication.run(LogosWebserviceApplication.class, args);
    }

}
