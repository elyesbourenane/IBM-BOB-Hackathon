package com.example.paymentclient.client;

import com.example.paymentclient.model.PaymentResponse;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import java.math.BigDecimal;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class PaymentClientTest {

    private PaymentClient paymentClient;
    private MockRestServiceServer mockServer;

    @BeforeEach
    void setUp() {
        RestClient.Builder builder = RestClient.builder();
        mockServer = MockRestServiceServer.bindTo(builder).build();
        paymentClient = new PaymentClient(builder, "http://localhost:8080");
    }

    @Test
    @DisplayName("Should successfully fetch payment via mocked HTTP endpoint")
    void testGetPayment() {
        String responseBody = """
                {
                    "id": "PAY-001",
                    "customerId": "CUST-123",
                    "paymentAmount": 100.00,
                    "currency": "EUR",
                    "status": "APPROVED"
                }
                """;

        mockServer.expect(requestTo("http://localhost:8080/api/payments/PAY-001"))
                .andExpect(method(HttpMethod.GET))
                .andRespond(withSuccess(responseBody, MediaType.APPLICATION_JSON));

        PaymentResponse response = paymentClient.getPayment("PAY-001");

        mockServer.verify();
        assertNotNull(response);
        assertEquals("PAY-001", response.getId());
        assertEquals("CUST-123", response.getCustomerId());
        assertEquals(new BigDecimal("100.00"), response.getPaymentAmount());
        assertEquals("EUR", response.getCurrency());
        assertEquals("APPROVED", response.getStatus());
    }

    @Test
    @DisplayName("Should demonstrate consumer expects and parses the totalAmount field from HTTP response")
    void testConsumerExpectsPaymentAmountFieldFromHttp() {
        String responseBody = """
                {
                    "id": "PAY-002",
                    "customerId": "CUST-456",
                    "paymentAmount": 250.00,
                    "currency": "USD",
                    "status": "PENDING"
                }
                """;

        mockServer.expect(requestTo("http://localhost:8080/api/payments/PAY-002"))
                .andExpect(method(HttpMethod.GET))
                .andRespond(withSuccess(responseBody, MediaType.APPLICATION_JSON));

        PaymentResponse response = paymentClient.getPayment("PAY-002");

        mockServer.verify();
        assertNotNull(response);
        assertNotNull(response.getPaymentAmount(), "paymentAmount field must be present and parsed by the consumer");
        assertEquals(new BigDecimal("250.00"), response.getPaymentAmount());
    }
}
