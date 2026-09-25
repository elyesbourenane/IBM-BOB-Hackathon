package com.example.paymentclient.client;

import com.example.paymentclient.model.PaymentResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

@Component
public class PaymentClient {

    private final RestClient restClient;

    public PaymentClient(RestClient.Builder restClientBuilder,
                         @Value("${payment.service.base-url:http://localhost:8080}") String baseUrl) {
        this.restClient = restClientBuilder
                .baseUrl(baseUrl)
                .build();
    }

    public PaymentResponse getPayment(String paymentId) {
        return restClient.get()
                .uri("/api/payments/{id}", paymentId)
                .accept(MediaType.APPLICATION_JSON)
                .retrieve()
                .body(PaymentResponse.class);
    }
}
