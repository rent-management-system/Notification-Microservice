@pytest.mark.asyncio
async def test_get_user_details_from_user_management_and_cache(mocker):
    user_id = UUID("123e4567-e89b-12d3-a456-426614174000")
    mock_user_data = {"email": "cached@example.com", "phone_number": "+251911123456", "preferred_language": "en"}

    # Mock httpx.AsyncClient.get to return user data
    mock_httpx_response = mocker.Mock()
    mock_httpx_response.status_code = 200
    mock_httpx_response.json.return_value = mock_user_data
    mocker.patch("httpx.AsyncClient.get", return_value=mock_httpx_response)

    # Mock redis client
    mock_redis_get = mocker.patch("redis.asyncio.Redis.get", return_value=None)
    mock_redis_setex = mocker.patch("redis.asyncio.Redis.setex")

    # First call: should fetch from user management and cache
    from app.services.notification import get_user_details_from_user_management
    user = await get_user_details_from_user_management(user_id)

    assert user == mock_user_data
    mock_httpx_response.json.assert_called_once() # Verify HTTP call
    mock_redis_get.assert_called_once_with(f"user_details:{user_id}")
    mock_redis_setex.assert_called_once()

    # Reset mocks for second call
    mock_httpx_response.json.reset_mock()
    mock_redis_get.reset_mock()
    mock_redis_setex.reset_mock()

    # Second call: should fetch from cache
    mock_redis_get.return_value = json.dumps(mock_user_data).encode('utf-8')
    user_cached = await get_user_details_from_user_management(user_id)

    assert user_cached == mock_user_data
    mock_httpx_response.json.assert_not_called() # Verify no HTTP call
    mock_redis_get.assert_called_once_with(f"user_details:{user_id}")
    mock_redis_setex.assert_not_called()

@pytest.mark.asyncio
async def test_circuit_breaker_open_and_block(mocker, caplog):
    from app.services.notification import send_email_ses, ses_circuit_breaker
    from app.utils.retry import CircuitBreakerOpenException
    from botocore.exceptions import ClientError

    # Reset circuit breaker state for this test
    ses_circuit_breaker.failures = 0
    ses_circuit_breaker.state = "CLOSED"
    ses_circuit_breaker.last_failure_time = None

    # Mock SES client to always fail
    mocker.patch("boto3.client.send_email", side_effect=ClientError({"Error": {"Code": "Throttling"}}, "SendEmail"))

    recipient = "test@example.com"
    subject = "Test"
    body = "Body"

    with caplog.at_level(logging.WARNING):
        for i in range(ses_circuit_breaker.failure_threshold):
            with pytest.raises(ClientError):
                await send_email_ses(recipient, subject, body)
        assert ses_circuit_breaker.state == "OPEN"
        assert "Circuit Breaker OPEN" in caplog.text

    caplog.clear()

    # Next call should be blocked by the open circuit
    with caplog.at_level(logging.WARNING):
        with pytest.raises(CircuitBreakerOpenException):
            await send_email_ses(recipient, subject, body)
        assert "Circuit Breaker OPEN, blocking call" in caplog.text

@pytest.mark.asyncio
async def test_circuit_breaker_half_open_and_close(mocker, caplog):
    from app.services.notification import send_email_ses, ses_circuit_breaker
    from app.utils.retry import CircuitBreakerOpenException
    from botocore.exceptions import ClientError

    # Set circuit breaker to OPEN state, but past reset_timeout
    ses_circuit_breaker.failures = ses_circuit_breaker.failure_threshold
    ses_circuit_breaker.state = "OPEN"
    ses_circuit_breaker.last_failure_time = datetime.utcnow() - timedelta(seconds=ses_circuit_breaker.reset_timeout + 1)

    # Mock SES client to succeed for the half-open trial
    mock_ses_send_email_success = mocker.patch("boto3.client.send_email", return_value={'MessageId': 'mock-success-id'})

    recipient = "test@example.com"
    subject = "Test"
    body = "Body"

    with caplog.at_level(logging.INFO):
        # First call should transition to HALF-OPEN and succeed
        message_id = await send_email_ses(recipient, subject, body)
        assert message_id == 'mock-success-id'
        assert ses_circuit_breaker.state == "CLOSED"
        assert "Circuit Breaker HALF-OPEN" in caplog.text
        assert "Circuit Breaker CLOSED" in caplog.text
        mock_ses_send_email_success.assert_called_once()

    caplog.clear()
    mock_ses_send_email_success.reset_mock()

    # Subsequent calls should now succeed with circuit closed
    message_id = await send_email_ses(recipient, subject, body)
    assert message_id == 'mock-success-id'
    assert ses_circuit_breaker.state == "CLOSED"
    mock_ses_send_email_success.assert_called_once()

@pytest.mark.asyncio
async def test_circuit_breaker_half_open_and_reopen(mocker, caplog):
    from app.services.notification import send_email_ses, ses_circuit_breaker
    from app.utils.retry import CircuitBreakerOpenException
    from botocore.exceptions import ClientError

    # Set circuit breaker to OPEN state, but past reset_timeout
    ses_circuit_breaker.failures = ses_circuit_breaker.failure_threshold
    ses_circuit_breaker.state = "OPEN"
    ses_circuit_breaker.last_failure_time = datetime.utcnow() - timedelta(seconds=ses_circuit_breaker.reset_timeout + 1)

    # Mock SES client to fail again for the half-open trial
    mocker.patch("boto3.client.send_email", side_effect=ClientError({"Error": {"Code": "Throttling"}}, "SendEmail"))

    recipient = "test@example.com"
    subject = "Test"
    body = "Body"

    with caplog.at_level(logging.WARNING):
        # First call should transition to HALF-OPEN and then immediately reopen due to failure
        with pytest.raises(ClientError):
            await send_email_ses(recipient, subject, body)
        assert ses_circuit_breaker.state == "OPEN"
        assert "Circuit Breaker HALF-OPEN" in caplog.text
        assert "Circuit Breaker OPEN" in caplog.text # Re-opened

    caplog.clear()

    # Next call should be blocked by the re-opened circuit
    with caplog.at_level(logging.WARNING):
        with pytest.raises(CircuitBreakerOpenException):
            await send_email_ses(recipient, subject, body)
        assert "Circuit Breaker OPEN, blocking call" in caplog.text

@pytest.mark.asyncio
async def test_template_version_logged_on_send(mocker, caplog, mock_db_session):
    from app.services.notification import send_notification_service, NOTIFICATION_TEMPLATES
    from app.schemas.notification import NotificationCreate
    from uuid import UUID
    import logging

    # Mock external dependencies
    mocker.patch("app.services.notification.get_user_details_from_user_management", return_value={
        "email": "test@example.com", "phone_number": "+251911123456", "preferred_language": "en"
    })
    mocker.patch("app.services.notification.send_email_ses", return_value="mock-ses-id")
    mocker.patch("app.services.notification.send_sms_mock", return_value=True)

    # Ensure template version is set for the test
    NOTIFICATION_TEMPLATES["version"] = "1.0"

    notification_data = NotificationCreate(
        user_id=UUID("123e4567-e89b-12d3-a456-426614174000"),
        event_type="payment_success",
        context={"property_title": "Test Property", "location": "Addis Ababa", "amount": 1000}
    )

    with caplog.at_level(logging.INFO):
        await send_notification_service(mock_db_session, notification_data.user_id, notification_data.event_type, notification_data.context)
        assert "Notification successfully sent" in caplog.text
        assert "template_version=1.0" in caplog.text

@pytest.mark.asyncio
async def test_retry_failure_alerts_admin(mocker, caplog, mock_db_session):
    from app.services.notification import retry_failed_notifications, Notification
    from uuid import UUID
    from datetime import datetime
    import logging

    # Mock SES client to always fail for resend attempts
    mocker.patch("app.services.notification.send_email_ses", side_effect=ClientError({"Error": {"Code": "Throttling"}}, "SendEmail"))
    mocker.patch("app.services.notification.send_sms_mock", return_value=False) # SMS also fails
    
    # Mock the admin alert email function
    mock_send_admin_alert_email = mocker.patch("app.services.notification.send_admin_alert_email", return_value="mock-admin-ses-id")

    # Create a failed notification that has reached its retry limit (attempts = 2, so next will be 3)
    failed_notification = Notification(
        id=UUID("a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a99"),
        user_id=UUID("123e4567-e89b-12d3-a456-426614174000"),
        event_type="payment_failed",
        status="FAILED",
        attempts=2,
        context={"property_title": "Failed Property", "location": "Addis Ababa", "amount": 500},
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow()
    )
    mock_db_session.add(failed_notification)
    await mock_db_session.commit()
    await mock_db_session.refresh(failed_notification)

    # Mock the select query to return our failed notification
    mocker.patch("sqlalchemy.ext.asyncio.AsyncSession.execute", return_value=mocker.AsyncMock(
        scalars=mocker.Mock(all=mocker.Mock(return_value=[failed_notification]))
    ))
    
    # Mock get_user_details_from_user_management to succeed
    mocker.patch("app.services.notification.get_user_details_from_user_management", return_value={
        "email": "test@example.com", "phone_number": "+251911123456", "preferred_language": "en"
    })

    with caplog.at_level(logging.CRITICAL):
        await retry_failed_notifications(mock_db_session)
        
        # Assert critical log is present
        assert "Notification permanently failed after 3 retries" in caplog.text
        assert f"notification_id={failed_notification.id}" in caplog.text
        
        # Assert admin alert email was sent
        mock_send_admin_alert_email.assert_called_once_with(
            subject=f"CRITICAL: Notification {failed_notification.id} permanently failed",
            body=mocker.ANY # Check content more specifically if needed
        )
    
    # Verify notification status is still FAILED after max attempts
    await mock_db_session.refresh(failed_notification)
    assert failed_notification.status == "FAILED"
    assert failed_notification.attempts == 3

@pytest.mark.asyncio
async def test_mock_sms_logging(mocker, caplog):
    from app.services.notification import send_sms_mock
    import logging

    phone_number = "+251911123456"
    message = "Test SMS message"

    with caplog.at_level(logging.INFO):
        result = await send_sms_mock(phone_number, message)
        assert result["status"] == "success"
        assert "mock_sms_sent" in caplog.text
        assert f"phone_number={phone_number}" in caplog.text
        assert f"message={message}" in caplog.text