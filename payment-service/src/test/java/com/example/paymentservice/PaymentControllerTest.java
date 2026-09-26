package com.example.paymentservice;

import com.example.paymentservice.repository.PaymentRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import static org.hamcrest.Matchers.is;
import static org.hamcrest.Matchers.notNullValue;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
class PaymentControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private PaymentRepository paymentRepository;

    @BeforeEach
    void setUp() {
        paymentRepository.reset();
    }

    @Test
    @DisplayName("Should successfully create a EUR payment")
    void testSuccessfulEurPayment() throws Exception {
        String requestJson = """
                {
                    "customerId": "CUST-123",
                    "amount": 150.00,
                    "currency": "EUR"
                }
                """;

        mockMvc.perform(post("/api/payments")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(requestJson))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.id", notNullValue()))
                .andExpect(jsonPath("$.customerId", is("CUST-123")))
                .andExpect(jsonPath("$.paymentAmount", is(150.00)))
                .andExpect(jsonPath("$.status", is("APPROVED")));
    }

    @Test
    @DisplayName("Should successfully create a USD payment")
    void testSuccessfulUsdPayment() throws Exception {
        String requestJson = """
                {
                    "customerId": "CUST-456",
                    "amount": 299.99,
                    "currency": "USD"
                }
                """;

        mockMvc.perform(post("/api/payments")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(requestJson))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.id", notNullValue()))
                .andExpect(jsonPath("$.customerId", is("CUST-456")))
                .andExpect(jsonPath("$.paymentAmount", is(299.99)))
                .andExpect(jsonPath("$.status", is("APPROVED")));
    }

    @Test
    @DisplayName("Should return 400 when customerId is blank or missing")
    void testInvalidCustomerId() throws Exception {
        String emptyCustomerIdJson = """
                {
                    "customerId": "   ",
                    "amount": 100.00,
                    "currency": "EUR"
                }
                """;

        mockMvc.perform(post("/api/payments")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(emptyCustomerIdJson))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.status", is(400)))
                .andExpect(jsonPath("$.errors.customerId", notNullValue()));

        String missingCustomerIdJson = """
                {
                    "amount": 100.00,
                    "currency": "EUR"
                }
                """;

        mockMvc.perform(post("/api/payments")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(missingCustomerIdJson))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.status", is(400)))
                .andExpect(jsonPath("$.errors.customerId", notNullValue()));
    }

    @Test
    @DisplayName("Should return 400 when amount is zero, negative, or missing")
    void testInvalidAmount() throws Exception {
        String zeroAmountJson = """
                {
                    "customerId": "CUST-123",
                    "amount": 0.00,
                    "currency": "EUR"
                }
                """;

        mockMvc.perform(post("/api/payments")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(zeroAmountJson))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.status", is(400)))
                .andExpect(jsonPath("$.errors.amount", notNullValue()));

        String negativeAmountJson = """
                {
                    "customerId": "CUST-123",
                    "amount": -50.00,
                    "currency": "EUR"
                }
                """;

        mockMvc.perform(post("/api/payments")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(negativeAmountJson))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.status", is(400)))
                .andExpect(jsonPath("$.errors.amount", notNullValue()));

        String missingAmountJson = """
                {
                    "customerId": "CUST-123",
                    "currency": "EUR"
                }
                """;

        mockMvc.perform(post("/api/payments")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(missingAmountJson))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.status", is(400)))
                .andExpect(jsonPath("$.errors.amount", notNullValue()));
    }

    @Test
    @DisplayName("Should return 400 when currency is missing")
    void testMissingCurrency() throws Exception {
        String missingCurrencyJson = """
                {
                    "customerId": "CUST-123",
                    "amount": 100.00
                }
                """;

        mockMvc.perform(post("/api/payments")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(missingCurrencyJson))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.status", is(400)))
                .andExpect(jsonPath("$.errors.currency", notNullValue()));
    }

    @Test
    @DisplayName("Should return 400 when currency is unsupported")
    void testUnsupportedCurrency() throws Exception {
        String unsupportedCurrencyJson = """
                {
                    "customerId": "CUST-123",
                    "amount": 100.00,
                    "currency": "GBP"
                }
                """;

        mockMvc.perform(post("/api/payments")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(unsupportedCurrencyJson))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.status", is(400)));
    }

    @Test
    @DisplayName("Should return existing payment PAY-001 with HTTP 200")
    void testGetExistingPayment() throws Exception {
        mockMvc.perform(get("/api/payments/PAY-001")
                        .accept(MediaType.APPLICATION_JSON))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id", is("PAY-001")))
                .andExpect(jsonPath("$.customerId", is("CUST-123")))
                .andExpect(jsonPath("$.paymentAmount", is(100.00)))
                .andExpect(jsonPath("$.status", is("APPROVED")));
    }

    @Test
    @DisplayName("Should return HTTP 404 for unknown payment ID")
    void testGetUnknownPayment() throws Exception {
        mockMvc.perform(get("/api/payments/PAY-UNKNOWN")
                        .accept(MediaType.APPLICATION_JSON))
                .andExpect(status().isNotFound())
                .andExpect(jsonPath("$.status", is(404)))
                .andExpect(jsonPath("$.message", is("Payment not found with id: PAY-UNKNOWN")));
    }
}
