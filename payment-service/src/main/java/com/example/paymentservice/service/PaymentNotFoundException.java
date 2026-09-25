package com.example.paymentservice.service;

public class PaymentNotFoundException extends RuntimeException {
    public PaymentNotFoundException(String id) {
        super("Payment not found with id: " + id);
    }
}
