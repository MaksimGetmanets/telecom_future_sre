package ru.telecom.sre.orders;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.delete;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.actuate.observability.AutoConfigureObservability;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;

@SpringBootTest
@AutoConfigureMockMvc
@AutoConfigureObservability
@ActiveProfiles("test")
class OrdersApiTest {

    @Autowired
    MockMvc mvc;

    @AfterEach
    void resetFaults() throws Exception {
        mvc.perform(delete("/fault")).andExpect(status().isOk());
    }

    @Test
    void createAndListOrder() throws Exception {
        mvc.perform(post("/orders")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"item\":\"book\",\"quantity\":2}"))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.id").exists());

        mvc.perform(get("/orders"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[?(@.item == 'book')]").isNotEmpty());
    }

    @Test
    void invalidOrderIsRejected() throws Exception {
        mvc.perform(post("/orders")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"item\":\"\",\"quantity\":0}"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void unknownOrderIsNotFound() throws Exception {
        mvc.perform(get("/orders/999999")).andExpect(status().isNotFound());
    }

    @Test
    void injectedFaultsAffectOrdersUntilReset() throws Exception {
        mvc.perform(post("/fault").param("errorRate", "1")).andExpect(status().isOk());
        mvc.perform(get("/orders")).andExpect(status().isInternalServerError());

        mvc.perform(delete("/fault")).andExpect(status().isOk());
        mvc.perform(get("/orders")).andExpect(status().isOk());
    }

    @Test
    void leakEndpointRetainsMemoryAndClears() throws Exception {
        mvc.perform(get("/leak").param("mb", "2"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.leakedMb").value(2));
        mvc.perform(delete("/leak"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.leakedMb").value(0));
    }

    @Test
    void latencyHistogramHasThreeHundredMsBucket() throws Exception {
        mvc.perform(get("/orders")).andExpect(status().isOk());
        String body = mvc.perform(get("/actuator/prometheus"))
                .andExpect(status().isOk())
                .andReturn().getResponse().getContentAsString();
        assertThat(body).contains("http_server_requests_seconds_bucket");
        assertThat(body).contains("le=\"0.3\"");
        assertThat(body).contains("application=\"orders\"");
    }
}
