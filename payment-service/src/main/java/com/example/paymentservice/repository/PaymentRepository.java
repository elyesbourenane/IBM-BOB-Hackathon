package com.example.paymentservice.repository;

import com.example.paymentservice.model.Payment;

import java.util.List;
import java.util.Optional;

public interface PaymentRepository {
    Optional<Payment> findById(String id);
    Payment save(Payment payment);
    List<Payment> findAll();
    void reset();
}
