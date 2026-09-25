package com.example.paymentservice.model;

import java.math.BigDecimal;
import java.util.Objects;

public class Payment {
    private String id;
    private String customerId;
    private BigDecimal amount;
    private Currency currency;
    private PaymentStatus status;

    public Payment() {
    }

    public Payment(String id, String customerId, BigDecimal amount, Currency currency, PaymentStatus status) {
        this.id = id;
        this.customerId = customerId;
        this.amount = amount;
        this.currency = currency;
        this.status = status;
    }

    public String getId() {
        return id;
    }

    public void setId(String id) {
        this.id = id;
    }

    public String getCustomerId() {
        return customerId;
    }

    public void setCustomerId(String customerId) {
        this.customerId = customerId;
    }

    public BigDecimal getAmount() {
        return amount;
    }

    public void setAmount(BigDecimal amount) {
        this.amount = amount;
    }

    public Currency getCurrency() {
        return currency;
    }

    public void setCurrency(Currency currency) {
        this.currency = currency;
    }

    public PaymentStatus getStatus() {
        return status;
    }

    public void setStatus(PaymentStatus status) {
        this.status = status;
    }

    @Override
    public boolean equals(Object o) {
        if (this == o) return true;
        if (o == null || getClass() != o.getClass()) return false;
        Payment payment = (Payment) o;
        return Objects.equals(id, payment.id) &&
                Objects.equals(customerId, payment.customerId) &&
                Objects.equals(amount, payment.amount) &&
                currency == payment.currency &&
                status == payment.status;
    }

    @Override
    public int hashCode() {
        return Objects.hash(id, customerId, amount, currency, status);
    }

    @Override
    public String toString() {
        return "Payment{" +
                "id='" + id + '\'' +
                ", customerId='" + customerId + '\'' +
                ", amount=" + amount +
                ", currency=" + currency +
                ", status=" + status +
                '}';
    }
}
