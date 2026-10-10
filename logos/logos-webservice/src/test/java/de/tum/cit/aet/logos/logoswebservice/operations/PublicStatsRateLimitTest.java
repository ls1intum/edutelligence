package de.tum.cit.aet.logos.logoswebservice.operations;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.test.context.TestPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import de.tum.cit.aet.logos.logoswebservice.TestContainersConfig;

/**
 * /public/stats takes no credential, so like /info every call from one
 * address is bounded: two allowed, the third a 429.
 */
@SpringBootTest
@AutoConfigureMockMvc
@Import(TestContainersConfig.class)
@TestPropertySource(properties = {
    "spring.liquibase.enabled=true",
    "spring.liquibase.change-log=classpath:liquibase/changelog/master.xml",
    "logos.rate-limiting.enabled=true",
    "logos.rate-limiting.public-endpoint-requests-per-minute=2"
})
class PublicStatsRateLimitTest {

    @Autowired MockMvc mvc;
    @MockitoBean JwtDecoder jwtDecoder;

    @Test
    void repeatedCallsFromOneAddressAreRateLimited() throws Exception {
        for (int i = 0; i < 2; i++) {
            mvc.perform(get("/public/stats")).andExpect(status().isOk());
        }

        mvc.perform(get("/public/stats"))
           .andExpect(status().isTooManyRequests())
           .andExpect(header().string("Retry-After", "60"));
    }
}
