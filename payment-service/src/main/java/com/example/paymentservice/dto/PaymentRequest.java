package com.example.paymentservice.dto;

import com.example.paymentservice.model.Currency;
import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

import java.math.BigDecimal;

@Schema(description = "Payment creation request payload")
public class PaymentRequest {

    @Schema(description = "Customer identifier", example = "CUST-123", requiredMode = Schema.RequiredMode.REQUIRED)
    @NotBlank(message = "customerId is required")
    private String customerId;

    @Schema(description = "Payment amount (must be greater than zero)", example = "150.00", requiredMode = Schema.RequiredMode.REQUIRED)
    @NotNull(message = "amount is required")
    @DecimalMin(value = "0.01", message = "amount must be greater than 0")
    private BigDecimal amount;

    @Schema(description = "Payment currency (EUR or USD)", example = "EUR", requiredMode = Schema.RequiredMode.REQUIRED)
    @NotNull(message = "currency is required")
    private Currency currency;

    public PaymentRequest() {
    }

    public PaymentRequest(String customerId, BigDecimal amount, Currency currency) {
        this.customerId = customerId;
        this.amount = amount;
        this.currency = currency;
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
}
