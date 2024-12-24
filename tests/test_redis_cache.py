import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch
from redis_cache import RedisCache

@pytest.fixture
def mock_redis():
    with patch('redis.Redis') as mock:
        yield mock

@pytest.fixture
def redis_cache(mock_redis):
    return RedisCache(host='localhost', port=6379, password='test')

def test_set_prices(redis_cache, mock_redis):
    now = datetime.now(timezone.utc)
    prices_data = [
        (now, 0.0049),
        (now - timedelta(hours=1), 0.0045)
    ]
    
    redis_cache.set_prices('us-west-1', 't2.micro', prices_data)
    
    # Verify Redis hset was called
    mock_redis.return_value.hset.assert_called_once()
    args = mock_redis.return_value.hset.call_args[1]
    
    # Check key format
    assert args['name'] == 'prices:us-west-1:t2.micro'
    
    # Verify data structure
    data = args['mapping']['data']
    assert 'prices' in data
    assert 'cached_at' in data
    assert len(data['prices']) == 2

def test_set_prices_empty(redis_cache, mock_redis):
    redis_cache.set_prices('us-west-1', 't2.micro', [])
    
    # Verify empty result is cached
    mock_redis.return_value.hset.assert_called_once()
    args = mock_redis.return_value.hset.call_args[1]
    data = args['mapping']['data']
    assert 'prices' in data
    assert len(data['prices']) == 0

def test_get_prices(redis_cache, mock_redis):
    now = datetime.now(timezone.utc)
    mock_data = {
        'data': {
            'cached_at': now.isoformat(),
            'prices': [
                {'price': 0.0049, 'timestamp': now.isoformat()},
                {'price': 0.0045, 'timestamp': (now - timedelta(hours=1)).isoformat()}
            ]
        }
    }
    mock_redis.return_value.hgetall.return_value = mock_data
    
    result = redis_cache.get_prices('us-west-1', 't2.micro')
    assert result is not None
    assert 'cached_at' in result
    assert 'prices' in result
    assert len(result['prices']) == 2

def test_get_prices_no_data(redis_cache, mock_redis):
    mock_redis.return_value.hgetall.return_value = None
    result = redis_cache.get_prices('us-west-1', 't2.micro')
    assert result is None

def test_get_prices_expired(redis_cache, mock_redis):
    old_time = datetime.now(timezone.utc) - timedelta(hours=2)
    mock_data = {
        'data': {
            'cached_at': old_time.isoformat(),
            'prices': [
                {'price': 0.0049, 'timestamp': old_time.isoformat()}
            ]
        }
    }
    mock_redis.return_value.hgetall.return_value = mock_data
    
    # With default expiry (10 minutes)
    result = redis_cache.get_prices('us-west-1', 't2.micro')
    assert result is None  # Should return None as data is expired
