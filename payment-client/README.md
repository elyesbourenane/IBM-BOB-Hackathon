# Payment Client

A standalone Java 21 / Spring Boot 3.3.x application representing a downstream consumer of the external Payment Service.

## Overview

- **Independent Consumer Application**: `payment-client` is maintained in its own dedicated repository, completely isolated from any producer source code.
- **External Producer Dependency**: This service consumes the REST API exposed by `payment-service`. The producer runs externally and is accessed exclusively via HTTP.
- **Contract-Driven Consumption**: The client application depends on a specific API contract.
- **Consumer Contract Reference**: The file [`contracts/payment-service.yaml`](contracts/payment-service.yaml) documents the consumer's current contract expectations for `GET /api/payments/{id}`. This file is not automatically synchronized with the producer to mirror real-world decoupling.

## Architecture

```
payment-service (External)
       ↓  HTTP / REST
payment-client (This Repository)
       ↓
PaymentClient (Spring RestClient)
       ↓
PaymentDisplayService
```

For full architectural details, see [docs/architecture.md](docs/architecture.md).

## Configuration

The external service location is configurable via `application.properties`:

```properties
payment.service.base-url=http://localhost:8080
server.port=8081
```

## Consumed Endpoints

### `GET /api/payments/{id}`
Expected response format:
```json
{
  "id": "PAY-001",
  "customerId": "CUST-123",
  "amount": 100.00,
  "currency": "EUR",
  "status": "APPROVED"
}
```

The consumer maps this response into its own internal [`PaymentResponse`](src/main/java/com/example/paymentclient/model/PaymentResponse.java) object containing:
- `id` (String)
- `customerId` (String)
- `amount` (BigDecimal)
- `currency` (String)
- `status` (String)

## How to Run

### Prerequisites
- Java 21
- Maven 3.9+

### Running the Client Application
```bash
mvn spring-boot:run
```

The application runs on port `8081` by default to avoid port collisions when running alongside `payment-service` locally.

## How to Test

Run the test suite:
```bash
mvn clean test
```

Build the package:
```bash
mvn clean package
```
