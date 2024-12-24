import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch
from api import app

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

@pytest.fixture
def mock_redis_cache():
    with patch('api.redis_cache') as mock:
        yield mock

@pytest.fixture
def mock_spot_service():
    with patch('api.spot_service') as mock:
        yield mock

def test_get_spot_prices_latest(client, mock_redis_cache, mock_spot_service):
    # Mock data
    now = datetime.now(timezone.utc)
    cached_data = {
        "cached_at": now.isoformat(),
        "prices": [
            {"price": 0.0049, "timestamp": now.isoformat()},
            {"price": 0.0045, "timestamp": (now - timedelta(hours=1)).isoformat()}
        ]
    }
    mock_redis_cache.get_prices.return_value = cached_data

    # Test without history parameter
    response = client.get('/spot-prices/us-west-1/t2.micro')
    assert response.status_code == 200
    data = response.get_json()
    
    # Check structure
    assert 'instance_type' in data
    assert 'region' in data
    assert 'latest_price' in data
    assert 'cached_at' in data
    assert 'source' in data
    assert 'price_history' not in data
    
    # Check values
    assert data['instance_type'] == 't2.micro'
    assert data['region'] == 'us-west-1'
    assert data['latest_price']['price'] == 0.0049
    assert data['source'] == 'cache'

def test_get_spot_prices_with_history(client, mock_redis_cache, mock_spot_service):
    # Mock data
    now = datetime.now(timezone.utc)
    cached_data = {
        "cached_at": now.isoformat(),
        "prices": [
            {"price": 0.0049, "timestamp": now.isoformat()},
            {"price": 0.0045, "timestamp": (now - timedelta(hours=1)).isoformat()}
        ]
    }
    mock_redis_cache.get_prices.return_value = cached_data

    # Test with history=true
    response = client.get('/spot-prices/us-west-1/t2.micro?history=true')
    assert response.status_code == 200
    data = response.get_json()
    
    # Check history is included
    assert 'price_history' in data
    assert len(data['price_history']) == 2
    assert data['price_history'][0]['price'] == 0.0049

def test_get_spot_prices_cache_miss(client, mock_redis_cache, mock_spot_service):
    # Mock cache miss
    mock_redis_cache.get_prices.return_value = None
    
    # Mock AWS data
    now = datetime.now(timezone.utc)
    aws_data = [
        (now, 0.0049),
        (now - timedelta(hours=1), 0.0045)
    ]
    mock_spot_service.get_spot_price_by_region.return_value = aws_data

    response = client.get('/spot-prices/us-west-1/t2.micro')
    assert response.status_code == 200
    data = response.get_json()
    
    # Check source is AWS
    assert data['source'] == 'aws'
    assert data['latest_price']['price'] == 0.0049

def test_get_spot_prices_no_data(client, mock_redis_cache, mock_spot_service):
    # Mock no data in cache and AWS
    mock_redis_cache.get_prices.return_value = None
    mock_spot_service.get_spot_price_by_region.return_value = []

    response = client.get('/spot-prices/us-west-1/t2.micro')
    assert response.status_code == 404
    data = response.get_json()
    assert 'error' in data
    assert data['error'] == 'No prices found'

def test_list_endpoints(client):
    response = client.get('/')
    assert response.status_code == 200
    data = response.get_json()
    
    # Check endpoints documentation
    assert 'endpoints' in data
    endpoints = data['endpoints']
    assert '/spot-prices/<region>/<instance_type>' in endpoints
    assert 'history' in endpoints['/spot-prices/<region>/<instance_type>']['parameters']

def test_health_check(client):
    response = client.get('/health')
    assert response.status_code == 200
    data = response.get_json()
    assert data['status'] == 'healthy'
