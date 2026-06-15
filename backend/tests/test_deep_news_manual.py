import sys
import os
import pytest
from unittest.mock import patch

# Add src to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.features.sentiment import scan_for_key_events

@pytest.fixture
def mock_config():
    return {
        "news": {
            "key_event_keywords": [
                "earnings", "results", "partnership"
            ]
        }
    }

@patch('src.utils.helpers.load_config')
def test_key_event_detection(mock_load_config, mock_config):
    mock_load_config.return_value = mock_config
    
    # Mock Headlines
    headlines = [
        {"title": "Company A announces Q3 Earnings Results tomorrow"},  # Should match 'Earnings', 'Results'
        {"title": "Company B enters strategic Partnership with X"},     # Should match 'Partnership'
        {"title": "Company C stock is Rated Buy by Analyst"},           # Should NOT match (unless 'Buy' is added)
        {"title": "Nothing interesting happening here"}
    ]

    # Scan
    events = scan_for_key_events(headlines)

    # Assertions
    assert ("earnings" in [e.lower() for e in events] or 
            "results" in [e.lower() for e in events])
    assert "partnership" in [e.lower() for e in events]
    assert "buy" not in [e.lower() for e in events]

