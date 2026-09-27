package com.example.paymentclient.model;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class PaymentResponseSerializationTest {

    private final ObjectMapper objectMapper = new ObjectMapper();

    @Test
    @DisplayName("Should correctly deserialize the expected API response JSON into PaymentResponse")
    void testDeserializeExpectedApiResponse() throws Exception {
        String json = """
                {
                  "id": "PAY-001",
                  "customerId": "CUST-123",
                  "totalAmount": 100.00,
                  "paymentStatus": "APPROVED"
                }
                """;

        PaymentResponse response = objectMapper.readValue(json, PaymentResponse.class);

        assertNotNull(response);
        assertEquals("PAY-001", response.getId());
        assertEquals("CUST-123", response.getCustomerId());
        assertEquals(new BigDecimal("100.00"), response.getTotalAmount());
        assertEquals("APPROVED", response.getStatus());
    }

    @Test
    @DisplayName("Should demonstrate that the consumer explicitly expects and relies on the totalAmount field")
    void testConsumerExpectsTotalAmountField() throws Exception {
        String json = """
                {
                  "id": "PAY-001",
                  "customerId": "CUST-123",
                  "totalAmount": 100.00,
                  "paymentStatus": "APPROVED"
                }
                """;

        PaymentResponse response = objectMapper.readValue(json, PaymentResponse.class);

        // Verification that totalAmount is present and can be processed numerically
        assertNotNull(response.getTotalAmount(), "Expected totalAmount field to be non-null in consumer response");
        assertEquals(new BigDecimal("100.00"), response.getTotalAmount());
        assertTrue(response.getTotalAmount().compareTo(BigDecimal.ZERO) > 0, "Consumer expects positive totalAmount value");

        // Verification that amount calculations work as expected in consumer logic
        BigDecimal taxCalculated = response.getTotalAmount().multiply(new BigDecimal("0.20"));
        assertEquals(new BigDecimal("20.0000"), taxCalculated);
    }
}
