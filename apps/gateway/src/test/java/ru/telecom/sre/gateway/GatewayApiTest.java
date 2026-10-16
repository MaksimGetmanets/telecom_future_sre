package ru.telecom.sre.gateway;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.actuate.observability.AutoConfigureObservability;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;

@SpringBootTest(properties = "orders.url=http://localhost:1")
@AutoConfigureMockMvc
@AutoConfigureObservability
class GatewayApiTest {

    @Autowired
    MockMvc mvc;

    @Test
    void slowSleepsRequestedTime() throws Exception {
        mvc.perform(get("/slow").param("ms", "50"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.sleptMs").value(50));
    }

    @Test
    void failAlwaysFailsWithProbabilityOne() throws Exception {
        mvc.perform(get("/fail").param("p", "1"))
                .andExpect(status().isInternalServerError());
    }

    @Test
    void failNeverFailsWithProbabilityZero() throws Exception {
        mvc.perform(get("/fail").param("p", "0"))
                .andExpect(status().isOk());
    }

    @Test
    void ordersUnavailableReturnsBadGateway() throws Exception {
        mvc.perform(get("/orders"))
                .andExpect(status().isBadGateway());
    }

    @Test
    void latencyHistogramHasThreeHundredMsBucket() throws Exception {
        mvc.perform(get("/fail").param("p", "0")).andExpect(status().isOk());
        String body = mvc.perform(get("/actuator/prometheus"))
                .andExpect(status().isOk())
                .andReturn().getResponse().getContentAsString();
        assertThat(body).contains("http_server_requests_seconds_bucket");
        assertThat(body).contains("le=\"0.3\"");
        assertThat(body).contains("application=\"gateway\"");
    }
}
