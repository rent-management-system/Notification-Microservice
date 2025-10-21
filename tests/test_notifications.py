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

    # Trigger 5 failures to open the circuit
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