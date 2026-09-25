package com.example.paymentservice.repository;

import com.example.paymentservice.model.Currency;
import com.example.paymentservice.model.Payment;
import com.example.paymentservice.model.PaymentStatus;
import jakarta.annotation.PostConstruct;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

@Repository
public class InMemoryPaymentRepository implements PaymentRepository {

    private final Map<String, Payment> payments = new ConcurrentHashMap<>();
    private final AtomicLong idSequence = new AtomicLong(2);

    @PostConstruct
    public void init() {
        seedInitialData();
    }

    private void seedInitialData() {
        payments.clear();
        payments.put("PAY-001", new Payment(
                "PAY-001",
                "CUST-123",
                new BigDecimal("100.00"),
                Currency.EUR,
                PaymentStatus.APPROVED
        ));
        payments.put("PAY-002", new Payment(
                "PAY-002",
                "CUST-456",
                new BigDecimal("250.00"),
                Currency.USD,
                PaymentStatus.PENDING
        ));
    }

    @Override
    public Optional<Payment> findById(String id) {
        if (id == null) {
            return Optional.empty();
        }
        return Optional.ofNullable(payments.get(id));
    }

    @Override
    public Payment save(Payment payment) {
        if (payment.getId() == null || payment.getId().isBlank()) {
            long nextId = idSequence.incrementAndGet();
            payment.setId(String.format("PAY-%03d", nextId));
        }
        payments.put(payment.getId(), payment);
        return payment;
    }

    @Override
    public List<Payment> findAll() {
        return new ArrayList<>(payments.values());
    }

    @Override
    public void reset() {
        idSequence.set(2);
        seedInitialData();
    }
}
