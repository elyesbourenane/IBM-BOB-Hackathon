package com.example.paymentservice.service;

import com.example.paymentservice.dto.PaymentRequest;
import com.example.paymentservice.dto.PaymentResponse;
import com.example.paymentservice.model.Currency;
import com.example.paymentservice.model.Payment;
import com.example.paymentservice.model.PaymentStatus;
import com.example.paymentservice.repository.PaymentRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import java.math.BigDecimal;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class PaymentServiceTest {

    @Mock
    private PaymentRepository paymentRepository;

    @InjectMocks
    private PaymentService paymentService;

    private Payment samplePayment;

    @BeforeEach
    void setUp() {
        samplePayment = new Payment(
                "PAY-001",
                "CUST-123",
                new BigDecimal("100.00"),
                Currency.EUR,
                PaymentStatus.APPROVED
        );
    }

    @Test
    @DisplayName("Should successfully retrieve payment by id")
    void testGetPaymentByIdSuccess() {
        when(paymentRepository.findById("PAY-001")).thenReturn(Optional.of(samplePayment));

        PaymentResponse response = paymentService.getPaymentById("PAY-001");

        assertNotNull(response);
        assertEquals("PAY-001", response.getId());
        assertEquals("CUST-123", response.getCustomerId());
        assertEquals(new BigDecimal("100.00"), response.getPaymentAmount());
        assertEquals(Currency.EUR, response.getCurrency());
        assertEquals(PaymentStatus.APPROVED, response.getStatus());
        verify(paymentRepository).findById("PAY-001");
    }

    @Test
    @DisplayName("Should throw PaymentNotFoundException when payment does not exist")
    void testGetPaymentByIdNotFound() {
        when(paymentRepository.findById("PAY-999")).thenReturn(Optional.empty());

        assertThrows(PaymentNotFoundException.class, () -> paymentService.getPaymentById("PAY-999"));
        verify(paymentRepository).findById("PAY-999");
    }

    @Test
    @DisplayName("Should create payment and return response with APPROVED status")
    void testCreatePayment() {
        PaymentRequest request = new PaymentRequest("CUST-123", new BigDecimal("150.00"), Currency.EUR);
        Payment saved = new Payment("PAY-003", "CUST-123", new BigDecimal("150.00"), Currency.EUR, PaymentStatus.APPROVED);

        when(paymentRepository.save(any(Payment.class))).thenReturn(saved);

        PaymentResponse response = paymentService.createPayment(request);

        assertNotNull(response);
        assertEquals("PAY-003", response.getId());
        assertEquals("CUST-123", response.getCustomerId());
        assertEquals(new BigDecimal("150.00"), response.getPaymentAmount());
        assertEquals(Currency.EUR, response.getCurrency());
        assertEquals(PaymentStatus.APPROVED, response.getStatus());
        verify(paymentRepository).save(any(Payment.class));
    }
}
