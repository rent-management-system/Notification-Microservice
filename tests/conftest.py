import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from app.main import app, get_db
from app.config import settings
from app.models.notification import Base
import asyncio

# Use a test database URL
TEST_DATABASE_URL = settings.DATABASE_URL.replace("public", "test_notifications")

@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"

@pytest.fixture(scope="session")
async def db_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Create a mock Users table for testing purposes
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS Users (
                id UUID PRIMARY KEY,
                email VARCHAR(255) NOT NULL,
                phone_number VARCHAR(50),
                preferred_language VARCHAR(10) DEFAULT 'en'
            );
        """)
        # Insert a mock user for testing
        await conn.execute("""
            INSERT INTO Users (id, email, phone_number, preferred_language) VALUES
            ('123e4567-e89b-12d3-a456-426614174000', 'test@example.com', '+251911123456', 'en')
            ON CONFLICT (id) DO NOTHING;
        """)
        await conn.execute("""
            INSERT INTO Users (id, email, phone_number, preferred_language) VALUES
            ('123e4567-e89b-12d3-a456-426614174001', 'amharic@example.com', '+251911123457', 'am')
            ON CONFLICT (id) DO NOTHING;
        """)
        await conn.execute("""
            INSERT INTO Users (id, email, phone_number, preferred_language) VALUES
            ('123e4567-e89b-12d3-a456-426614174002', 'oromo@example.com', '+251911123458', 'om')
            ON CONFLICT (id) DO NOTHING;
        """)
    yield engine
    async with engine.begin() as conn:
        await conn.execute("DROP TABLE IF EXISTS Users CASCADE;")
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()

@pytest.fixture(scope="function")
async def db_session(db_engine):
    async_session = sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session
        await session.rollback() # Rollback after each test to ensure clean state

@pytest.fixture(scope="function")
async def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()

@pytest.fixture
def mock_user_management_verify(mocker):
    # Mock the httpx.AsyncClient.post call for user management verification
    mock_response = mocker.Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "user_id": "123e4567-e89b-12d3-a456-426614174000",
        "role": "Admin",
        "email": "test@example.com",
        "phone_number": "+251911123456",
        "preferred_language": "en"
    }
    mocker.patch("httpx.AsyncClient.post", return_value=mock_response)
    return mock_response

@pytest.fixture
def mock_ses_send_email(mocker):
    mock_boto_client = mocker.Mock()
    mock_boto_client.send_email.return_value = {'MessageId': 'mock-message-id'}
    mocker.patch("boto3.client", return_value=mock_boto_client)
    return mock_boto_client

@pytest.fixture
def mock_sms_send(mocker):
    mock_sms = mocker.patch("app.services.notification.send_sms_mock", return_value=True)
    return mock_sms
