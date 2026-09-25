package com.example.paymentclient.service;

import com.example.paymentclient.client.PaymentClient;
import com.example.paymentclient.model.PaymentResponse;
import org.springframework.stereotype.Service;

@Service
public class PaymentDisplayService {

    private final PaymentClient paymentClient;

    public PaymentDisplayService(PaymentClient paymentClient) {
        this.paymentClient = paymentClient;
    }

    public PaymentResponse fetchPayment(String paymentId) {
        return paymentClient.getPayment(paymentId);
    }

    public String formatPaymentSummary(String paymentId) {
        PaymentResponse payment = paymentClient.getPayment(paymentId);
        if (payment == null) {
            return "Payment not found: " + paymentId;
        }
        return String.format(
                "Payment [%s]: Amount %s %s for customer %s (Status: %s)",
                payment.getId(),
                payment.getTotalAmount() != null ? payment.getTotalAmount().toPlainString() : "N/A",
                payment.getCurrency(),
                payment.getCustomerId(),
                payment.getStatus()
        );
    }
}
