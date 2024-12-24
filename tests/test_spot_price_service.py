import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch
from spot_price_service import SpotPriceService

@pytest.fixture
def mock_session():
    return Mock()

@pytest.fixture
def mock_cache():
    return Mock()

@pytest.fixture
def spot_service(mock_session, mock_cache):
    return SpotPriceService(session=mock_session, cache=mock_cache)

def test_get_spot_price_by_region(spot_service, mock_session):
    # Mock AWS response
    now = datetime.now(timezone.utc)
    mock_response = {
        'SpotPriceHistory': [
            {
                'InstanceType': 't2.micro',
                'SpotPrice': '0.0049',
                'Timestamp': now
            },
            {
                'InstanceType': 't2.micro',
                'SpotPrice': '0.0045',
                'Timestamp': now - timedelta(hours=1)
            }
        ]
    }
    mock_session.client.return_value.describe_spot_price_history.return_value = mock_response
    
    result = spot_service.get_spot_price_by_region('t2.micro', 'us-west-1')
    
    # Check result format
    assert len(result) == 2
    assert isinstance(result[0], tuple)
    assert isinstance(result[0][0], datetime)
    assert isinstance(result[0][1], float)
    
    # Check values
    assert result[0][1] == 0.0049
    assert result[1][1] == 0.0045

def test_get_spot_price_by_region_no_prices(spot_service, mock_session):
    # Mock empty response
    mock_response = {'SpotPriceHistory': []}
    mock_session.client.return_value.describe_spot_price_history.return_value = mock_response
    
    result = spot_service.get_spot_price_by_region('t2.micro', 'us-west-1')
    assert result == []

def test_get_spot_price_by_region_error(spot_service, mock_session):
    # Mock AWS error
    mock_session.client.return_value.describe_spot_price_history.side_effect = Exception('AWS Error')
    
    result = spot_service.get_spot_price_by_region('t2.micro', 'us-west-1')
    assert result == []

def test_get_spot_price_by_region_sorts_by_time(spot_service, mock_session):
    # Mock response with unordered timestamps
    now = datetime.now(timezone.utc)
    mock_response = {
        'SpotPriceHistory': [
            {
                'InstanceType': 't2.micro',
                'SpotPrice': '0.0045',
                'Timestamp': now - timedelta(hours=1)
            },
            {
                'InstanceType': 't2.micro',
                'SpotPrice': '0.0049',
                'Timestamp': now
            }
        ]
    }
    mock_session.client.return_value.describe_spot_price_history.return_value = mock_response
    
    result = spot_service.get_spot_price_by_region('t2.micro', 'us-west-1')
    
    # Check results are sorted by timestamp (newest first)
    assert result[0][1] == 0.0049
    assert result[1][1] == 0.0045
