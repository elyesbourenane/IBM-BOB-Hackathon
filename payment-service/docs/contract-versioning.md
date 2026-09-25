# Contract Versioning Strategy

## Overview

In a microservices architecture, services often evolve independently across separate source repositories. `payment-service` acts as a producer service providing a REST API to external clients.

## Key Principles

1. **Independent Repositories**:
   The API contract published by `payment-service` is consumed by independent repositories (such as `payment-client`). There is no shared code repository, no parent POM, and no binary library dependency between producer and consumer.

2. **Impact of Changes on External Consumers**:
   Changes to the API endpoints, request schemas, or response schemas can directly impact external consumers. Breaking changes (such as renaming fields, altering field data types, removing fields, or adding mandatory request parameters) will cause consumer runtime failures if not coordinated or versioned properly.

3. **Published Producer Contract (`docs/openapi.yaml`)**:
   The file [`docs/openapi.yaml`](openapi.yaml) represents the currently published, baseline contract for `payment-service`. This committed document serves as the single source of truth for the API surface exposed by this service.

4. **Consumer Autonomy**:
   Consumers maintain their own representation of the contract they depend on (e.g. `payment-client/contracts/payment-service.yaml`). The producer must remain conscious that existing consumers might only support the current contract version.

5. **Stability & Backward Compatibility**:
   In this initial baseline release, no breaking changes are introduced. The contract defines:
   - `POST /api/payments` accepting `customerId`, `amount`, and `currency`.
   - `GET /api/payments/{id}` returning `id`, `customerId`, `amount`, `currency`, and `status`.
