# Payment Service

A standalone Java 21 / Spring Boot 3.3.x REST microservice that processes and retrieves payments.

## Purpose

`payment-service` serves as the producer in a decoupled microservices architecture. It provides an HTTP REST API for creating new payments and looking up existing payments. Downstream consumers (such as `payment-client`) consume these endpoints independently.

## Architecture

The service adheres to a standard layered design:

```
Controller (PaymentController)
    ↓
Service (PaymentService)
    ↓
Repository (InMemoryPaymentRepository)
```

- **Controller**: Manages HTTP request routing, input validation (`@Valid`), and response formatting.
- **Service**: Implements core business logic and maps between domain entities and DTOs.
- **Repository**: Provides thread-safe, in-memory storage seeded with deterministic data for consistent operation.

For an architectural diagram and consumer relationships, see [docs/architecture.md](docs/architecture.md).

## API Endpoints

### 1. Create Payment
- **Method**: `POST`
- **Path**: `/api/payments`
- **Request Body**:
  ```json
  {
    "customerId": "CUST-123",
    "amount": 150.00,
    "currency": "EUR"
  }
  ```
- **Response** (`201 Created`):
  ```json
  {
    "id": "PAY-003",
    "customerId": "CUST-123",
    "amount": 150.00,
    "currency": "EUR",
    "status": "APPROVED"
  }
  ```

### 2. Get Payment by ID
- **Method**: `GET`
- **Path**: `/api/payments/{id}`
- **Response** (`200 OK`):
  ```json
  {
    "id": "PAY-001",
    "customerId": "CUST-123",
    "amount": 100.00,
    "currency": "EUR",
    "status": "APPROVED"
  }
  ```

### Validation Rules
- `customerId`: Required, non-blank string.
- `amount`: Required numeric value strictly greater than 0.
- `currency`: Required, must be either `EUR` or `USD`.
- Returns `400 Bad Request` if any validation constraint fails.
- Returns `404 Not Found` if payment ID does not exist.

### Pre-seeded Deterministic Data
- `PAY-001`: `customerId="CUST-123"`, `amount=100.00`, `currency=EUR`, `status=APPROVED`
- `PAY-002`: `customerId="CUST-456"`, `amount=250.00`, `currency=USD`, `status=PENDING`

## API Contract

The static OpenAPI 3.0 contract representing the baseline API specification is maintained at:
- [docs/openapi.yaml](docs/openapi.yaml)

When the service is running, the interactive Swagger UI and OpenAPI JSON documents are accessible at:
- Swagger UI: `http://localhost:8080/swagger-ui.html`
- OpenAPI JSON: `http://localhost:8080/v3/api-docs`

For details on how contract versioning and consumer decoupling are managed, see [docs/contract-versioning.md](docs/contract-versioning.md).

## How to Run

### Prerequisites
- Java 21
- Maven 3.9+

### Running the Application
```bash
mvn spring-boot:run
```

The service will start on port `8080`.

## How to Test

Run the full automated test suite:
```bash
mvn clean test
```

Build the production package:
```bash
mvn clean package
```
