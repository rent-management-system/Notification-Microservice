# Notification Microservice

This microservice handles sending notifications (email, SMS) for a Rental Management System. It integrates with User Management, Payment Processing, and Property Listing services.

## Features

- Send notifications for various events (payment success/failure, listing approval, tenant updates).
- Multilingual templates (English, Amharic, Afaan Oromo) based on user's preferred language.
- Notification logging for auditing and retries.
- Admin endpoints for viewing and managing notifications.
- Secure with JWT authentication and Pydantic validation.
- Rate limiting for `/send` endpoint.
- Asynchronous operations with `asyncpg` and `FastAPI`.
- Retry mechanism for failed notification sends.

## Demo Flow Diagram

```
+-------------------+     +-------------------+     +-------------------+
|   User Service    |     |  Payment Service  |     |  Property Service |
| (Manages Users)   |     | (Handles Payments)|     | (Manages Listings)|
+---------+---------+     +---------+---------+     +---------+---------+
          |                       |                       |
          | 1. User Registration  | 2. Payment Event      | 3. Listing Update
          | (New User)            | (Success/Failure)     | (Approval/Change)
          v                       v                       v
+-----------------------------------------------------------------------+
|                     Notification Microservice                         |
| (Sends Emails/SMS based on events, integrates with external services) |
+-----------------------------------------------------------------------+
          |
          | 4. Notification Trigger (Internal API Call)
          v
+-------------------+     +-------------------+
|     AWS SES       |     |     Mock SMS      |
| (Sends Emails)    |     | (Simulates SMS)   |
+-------------------+     +-------------------+
```

## Technologies Used

- Python 3.10+
- FastAPI
- PostgreSQL (asyncpg)
- SQLAlchemy (ORM)
- AWS SES (for email)
- `httpx` (for internal service calls)
- `python-jose` (for JWT)
- `apscheduler` (for cron jobs)
- `structlog` (for structured logging)
- `fastapi-limiter` (for rate limiting)
- `boto3` (for AWS SES)

## Setup

1.  **Clone the repository:**
    ```bash
    git clone <repository_url>
    cd Notification Microservice
    ```

2.  **Create and activate a virtual environment:**
    ```bash
    python3.10 -m venv venv
    source venv/bin/activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configure environment variables:**
    Copy `.env.example` to `.env` and fill in the details.

    ```bash
    cp .env.example .env
    ```

    Edit `.env`:
    ```
    DATABASE_URL="postgresql+asyncpg://user:password@host:port/database"
    USER_MANAGEMENT_URL="http://user-management:8000/api/v1"
    AWS_ACCESS_KEY_ID="YOUR_AWS_ACCESS_KEY_ID"
    AWS_SECRET_ACCESS_KEY="YOUR_AWS_SECRET_ACCESS_KEY"
    AWS_REGION_NAME="us-east-1"
    JWT_SECRET="YOUR_SUPER_SECRET_JWT_KEY"
    ALGORITHM="HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES=30
    ```

5.  **Run Migrations and Seed Data:**
    Ensure your PostgreSQL database is running and accessible via `DATABASE_URL`.
    ```bash
    chmod +x migrate.sh
    ./migrate.sh
    ```

6.  **Run the application:**
    ```bash
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
    ```
    The API documentation will be available at `http://localhost:8000/docs`.

## API Endpoints

### Send Notification

-   **Method:** `POST`
-   **Path:** `/api/v1/notifications/send`
-   **Permissions:** Admin or Internal Services
-   **Description:** Sends an email/SMS notification for a specific event to a user.
-   **Parameters (Request Body):**
    ```json
    {
        "user_id": "UUID",
        "event_type": "str",
        "context": "dict"
    }
    ```
    Example `context`: `{"property_title": "Luxury Apartment", "location": "Addis Ababa", "amount": 1500}`
-   **Example Response:**
    ```json
    {
        "status": "sent",
        "notification_id": "UUID"
    }
    ```

### Get Notification by ID

-   **Method:** `GET`
-   **Path:** `/api/v1/notifications/{id}`
-   **Permissions:** Admin
-   **Description:** Retrieves details of a specific notification.
-   **Example Response:**
    ```json
    {
        "id": "UUID",
        "user_id": "UUID",
        "event_type": "str",
        "status": "str",
        "sent_at": "datetime"
    }
    ```

### Get All Notifications

-   **Method:** `GET`
-   **Path:** `/api/v1/notifications`
-   **Permissions:** Admin
-   **Description:** Retrieves a list of notifications, with optional filtering.
-   **Query Parameters:**
    -   `user_id`: `UUID` (Optional)
    -   `event_type`: `str` (Optional)
-   **Example Response:**
    ```json
    [
        {
            "id": "UUID",
            "user_id": "UUID",
            "event_type": "str",
            "status": "str",
            "sent_at": "datetime"
        }
    ]
    ```

### Get Notification Statistics

-   **Method:** `GET`
-   **Path:** `/api/v1/notifications/stats`
-   **Permissions:** Admin
-   **Description:** Retrieves aggregated statistics about notifications.
-   **Example Response:**
    ```json
    {
        "total_notifications": 105,
        "total_sent": 50,
        "total_failed": 30,
        "total_pending": 25,
        "by_status": {
            "SENT": 50,
            "FAILED": 30,
            "PENDING": 25
        },
        "by_event_type": {
            "payment_success": {
                "SENT": 20,
                "FAILED": 10,
                "PENDING": 5
            },
            "listing_approved": {
                "SENT": 15,
                "FAILED": 5,
                "PENDING": 10
            },
            "payment_failed": {
                "SENT": 5,
                "FAILED": 10,
                "PENDING": 5
            },
            "tenant_update": {
                "SENT": 10,
                "FAILED": 5,
                "PENDING": 5
            }
        }
    }
    ```

    **ASCII Chart (Sample Data):**
    ```
    Total:   |||||||||| 105
    Sent:    ||||||||| 50
    Failed:  |||||| 30
    Pending: ||||| 25
    ```

### Retry Failed Notifications

-   **Method:** `POST`
-   **Path:** `/api/v1/notifications/retry`
-   **Permissions:** Internal (typically called by a cron job)
-   **Description:** Retries sending failed notifications.

## Demo Walkthrough

1.  **Start the services:** Ensure User Management and Notification Microservices are running.
2.  **Seed Data:** Run `./migrate.sh` to create the `Notifications` table and seed it with test data.
3.  **Send a test notification (as Admin/Internal):**
    ```bash
    curl -X POST "http://localhost:8000/api/v1/notifications/send" \
         -H "Authorization: Bearer YOUR_ADMIN_JWT_TOKEN" \
         -H "Content-Type: application/json" \
         -d '{
               "user_id": "a1b2c3d4-e5f6-7890-1234-567890abcdef",
               "event_type": "payment_success",
               "context": {
                 "property_title": "Modern Studio",
                 "location": "Bole, Addis Ababa",
                 "amount": 2500
               }
             }'
    ```
    *(Replace `YOUR_ADMIN_JWT_TOKEN` and `user_id` with actual values from your User Management service.)*

4.  **View notifications (as Admin):**
    ```bash
    curl -X GET "http://localhost:8000/api/v1/notifications" \
         -H "Authorization: Bearer YOUR_ADMIN_JWT_TOKEN"
    ```

5.  **View a specific notification (as Admin):**
    ```bash
    curl -X GET "http://localhost:8000/api/v1/notifications/YOUR_NOTIFICATION_ID" \
         -H "Authorization: Bearer YOUR_ADMIN_JWT_TOKEN"
    ```

6.  **Trigger retry (simulated cron job):**
    ```bash
    curl -X POST "http://localhost:8000/api/v1/notifications/retry" \
         -H "Authorization: Bearer YOUR_INTERNAL_SERVICE_JWT_TOKEN"
    ```
    *(This endpoint is typically called by `apscheduler` internally, but can be triggered manually for testing.)*

### Demonstrating Error Scenarios

To showcase the robustness and error handling of the microservice, you can simulate the following scenarios:

1.  **Unauthorized Access (403 Forbidden):**
    Attempt to access an admin-only endpoint (e.g., `/stats`) with a non-admin JWT token.

    ```bash
    # Ensure you have a non-admin JWT token for this test
    curl -X GET "http://localhost:8000/api/v1/notifications/stats" \
         -H "Authorization: Bearer YOUR_NON_ADMIN_JWT_TOKEN"
    ```
    *Expected Response:* `{"detail":"Forbidden"}`

2.  **Send to a Non-Existent User (404 Not Found):**
    Attempt to send a notification to a `user_id` that does not exist in the `Users` table.

    ```bash
    curl -X POST "http://localhost:8000/api/v1/notifications/send" \
         -H "Authorization: Bearer YOUR_ADMIN_JWT_TOKEN" \
         -H "Content-Type: application/json" \
         -d '{
               "user_id": "00000000-0000-0000-0000-000000000000",
               "event_type": "payment_success",
               "context": {
                 "property_title": "Non-existent User Test",
                 "location": "Unknown",
                 "amount": 100
               }
             }'
    ```
    *Expected Response:* `{"detail":"User with ID 00000000-0000-0000-0000-000000000000 not found."}`
    *(This will also log a FAILED notification in the database.)*

3.  **Trigger Rate Limit (429 Too Many Requests):**
    Rapidly execute the `POST /api/v1/notifications/send` command more than 10 times within a minute.

    ```bash
    # Run this command in a loop or multiple times in quick succession
    for i in {1..15}; do
      curl -X POST "http://localhost:8000/api/v1/notifications/send" \
           -H "Authorization: Bearer YOUR_ADMIN_JWT_TOKEN" \
           -H "Content-Type: application/json" \
           -d '{
                 "user_id": "123e4567-e89b-12d3-a456-426614174000",
                 "event_type": "listing_approved",
                 "context": { "property_title": "Rate Limit Test", "location": "Fast Lane" }
               }' &
    done
    ```
    *Expected Response (after 10 requests):* `{"error":"Too Many Requests"}`

4.  **Simulate SES Failure and Retry:**
    To demonstrate SES failure and the retry mechanism, you can temporarily provide invalid AWS credentials in your `.env` file (e.g., `AWS_ACCESS_KEY_ID="INVALID"`).
    - Send a notification. The initial request will hang for a moment and then log a `FAILED` notification.
    - The `apscheduler` job running `retry_failed_notifications` will automatically pick up this failed notification every 5 minutes.
    - Check the logs to see the retry attempts. After 3 failed attempts, the notification will be permanently marked as failed.


## Deployment on AWS ECS/Fargate


The `Dockerfile` is configured for containerized deployment. You can build and push this image to AWS ECR, then deploy it as a service on AWS ECS/Fargate. Ensure your ECS Task Definition includes the necessary environment variables from `.env` and IAM roles for AWS SES access.

## Test Coverage

To run tests:
```bash
pytest
```
