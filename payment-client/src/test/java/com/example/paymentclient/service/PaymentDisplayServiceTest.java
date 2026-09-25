package com.example.paymentclient.service;

import com.example.paymentclient.client.PaymentClient;
import com.example.paymentclient.model.PaymentResponse;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class PaymentDisplayServiceTest {

    @Mock
    private PaymentClient paymentClient;

    @InjectMocks
    private PaymentDisplayService paymentDisplayService;

    @Test
    @DisplayName("Should successfully consume and display formatted payment summary")
    void testFormatPaymentSummary() {
        PaymentResponse response = new PaymentResponse(
                "PAY-001",
                "CUST-123",
                new BigDecimal("100.00"),
                "EUR",
                "APPROVED"
        );

        when(paymentClient.getPayment("PAY-001")).thenReturn(response);

        String summary = paymentDisplayService.formatPaymentSummary("PAY-001");

        assertNotNull(summary);
        assertTrue(summary.contains("PAY-001"));
        assertTrue(summary.contains("100.00"));
        assertTrue(summary.contains("EUR"));
        assertTrue(summary.contains("CUST-123"));
        assertTrue(summary.contains("APPROVED"));

        verify(paymentClient).getPayment("PAY-001");
    }

    @Test
    @DisplayName("Should successfully fetch payment entity via display service")
    void testFetchPayment() {
        PaymentResponse response = new PaymentResponse(
                "PAY-001",
                "CUST-123",
                new BigDecimal("100.00"),
                "EUR",
                "APPROVED"
        );

        when(paymentClient.getPayment("PAY-001")).thenReturn(response);

        PaymentResponse result = paymentDisplayService.fetchPayment("PAY-001");

        assertNotNull(result);
        assertEquals("PAY-001", result.getId());
        assertEquals(new BigDecimal("100.00"), result.getTotalAmount());
        verify(paymentClient).getPayment("PAY-001");
    }
}
