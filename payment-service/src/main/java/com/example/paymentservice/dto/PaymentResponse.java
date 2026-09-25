package com.example.paymentservice.dto;

import com.example.paymentservice.model.Currency;
import com.example.paymentservice.model.Payment;
import com.example.paymentservice.model.PaymentStatus;
import io.swagger.v3.oas.annotations.media.Schema;

import java.math.BigDecimal;
import java.util.Objects;

@Schema(description = "Payment response representation")
public class PaymentResponse {

    @Schema(description = "Unique payment identifier", example = "PAY-001", requiredMode = Schema.RequiredMode.REQUIRED)
    private String id;

    @Schema(description = "Customer identifier", example = "CUST-123", requiredMode = Schema.RequiredMode.REQUIRED)
    private String customerId;

    @Schema(description = "Payment amount", example = "150.00", requiredMode = Schema.RequiredMode.REQUIRED)
    private BigDecimal totalAmount;

    @Schema(description = "Payment currency", example = "EUR", requiredMode = Schema.RequiredMode.REQUIRED)
    private Currency currency;

    @Schema(description = "Payment status", example = "APPROVED", requiredMode = Schema.RequiredMode.REQUIRED)
    private PaymentStatus status;

    public PaymentResponse() {
    }

    public PaymentResponse(String id, String customerId, BigDecimal totalAmount, Currency currency, PaymentStatus status) {
        this.id = id;
        this.customerId = customerId;
        this.totalAmount = totalAmount;
        this.currency = currency;
        this.status = status;
    }

    public static PaymentResponse fromDomain(Payment payment) {
        return new PaymentResponse(
                payment.getId(),
                payment.getCustomerId(),
                payment.getAmount(),
                payment.getCurrency(),
                payment.getStatus()
        );
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

    public BigDecimal getTotalAmount() {
        return totalAmount;
    }

    public void setTotalAmount(BigDecimal totalAmount) {
        this.totalAmount = totalAmount;
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
        PaymentResponse that = (PaymentResponse) o;
        return Objects.equals(id, that.id) &&
                Objects.equals(customerId, that.customerId) &&
                Objects.equals(totalAmount, that.totalAmount) &&
                currency == that.currency &&
                status == that.status;
    }

    @Override
    public int hashCode() {
        return Objects.hash(id, customerId, totalAmount, currency, status);
    }

    @Override
    public String toString() {
        return "PaymentResponse{" +
                "id='" + id + '\'' +
                ", customerId='" + customerId + '\'' +
                ", totalAmount=" + totalAmount +
                ", currency=" + currency +
                ", status=" + status +
                '}';
    }
}
