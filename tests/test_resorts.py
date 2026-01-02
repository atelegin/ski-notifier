"""Tests for resort data loading and validation."""

from pathlib import Path
from unittest.mock import patch, mock_open
import yaml

import pytest

from ski_notifier.resorts import (
    load_resorts,
    _is_valid_coordinates,
    LoadResult,
)


class TestCoordinateValidation:
    """Tests for coordinate validation."""
    
    def test_valid_european_coordinates(self):
        """Should accept valid European coordinates."""
        assert _is_valid_coordinates(47.5, 8.5) is True
        assert _is_valid_coordinates(46.0, 10.0) is True
    
    def test_valid_extreme_coordinates(self):
        """Should accept extreme but valid coordinates."""
        assert _is_valid_coordinates(90.0, 180.0) is True
        assert _is_valid_coordinates(-90.0, -180.0) is True
    
    def test_invalid_latitude_too_high(self):
        """Should reject latitude > 90."""
        assert _is_valid_coordinates(91.0, 8.0) is False
    
    def test_invalid_latitude_too_low(self):
        """Should reject latitude < -90."""
        assert _is_valid_coordinates(-91.0, 8.0) is False
    
    def test_invalid_longitude_too_high(self):
        """Should reject longitude > 180."""
        assert _is_valid_coordinates(47.0, 181.0) is False
    
    def test_invalid_longitude_too_low(self):
        """Should reject longitude < -180."""
        assert _is_valid_coordinates(47.0, -181.0) is False


class TestLoadResorts:
    """Tests for load_resorts function."""
    
    def test_skips_resort_with_invalid_latitude(self, tmp_path):
        """Should skip resort with latitude out of range."""
        yaml_content = """
schema_version: 1
defaults:
  costs:
    ferry_roundtrip_eur: 24.2
    austria_vignette_1day_eur: 9.6
resorts:
  - id: invalid_resort
    name: Invalid Resort
    country: CH
    type: alpine
    drive_time_min_from_konstanz: 60
    points:
      low:
        lat: 999.0
        lon: 8.0
      high:
        lat: 47.5
        lon: 8.5
  - id: valid_resort
    name: Valid Resort
    country: CH
    type: alpine
    drive_time_min_from_konstanz: 60
    points:
      low:
        lat: 47.0
        lon: 8.0
      high:
        lat: 47.5
        lon: 8.5
"""
        yaml_path = tmp_path / "test_resorts.yaml"
        yaml_path.write_text(yaml_content)
        
        result = load_resorts(yaml_path)
        
        assert result.n_skipped == 1
        assert "invalid_resort" in result.skipped_ids
        assert len(result.resorts) == 1
        assert result.resorts[0].id == "valid_resort"
    
    def test_skips_resort_with_invalid_longitude(self, tmp_path):
        """Should skip resort with longitude out of range."""
        yaml_content = """
schema_version: 1
defaults:
  costs: {}
resorts:
  - id: bad_lon_resort
    name: Bad Lon Resort
    country: CH
    type: alpine
    drive_time_min_from_konstanz: 60
    points:
      low:
        lat: 47.0
        lon: 8.0
      high:
        lat: 47.5
        lon: 200.0
"""
        yaml_path = tmp_path / "test_resorts.yaml"
        yaml_path.write_text(yaml_content)
        
        result = load_resorts(yaml_path)
        
        assert result.n_skipped == 1
        assert "bad_lon_resort" in result.skipped_ids
        assert len(result.resorts) == 0
    
    def test_loads_valid_resorts(self, tmp_path):
        """Should load all valid resorts."""
        yaml_content = """
schema_version: 1
defaults:
  costs:
    ferry_roundtrip_eur: 24.2
resorts:
  - id: resort_a
    name: Resort A
    country: CH
    type: alpine
    drive_time_min_from_konstanz: 60
    points:
      low:
        lat: 47.0
        lon: 8.0
      high:
        lat: 47.5
        lon: 8.5
  - id: resort_b
    name: Resort B
    country: AT
    type: xc
    drive_time_min_from_konstanz: 90
    points:
      low:
        lat: 47.2
        lon: 9.0
      high:
        lat: 47.6
        lon: 9.5
"""
        yaml_path = tmp_path / "test_resorts.yaml"
        yaml_path.write_text(yaml_content)
        
        result = load_resorts(yaml_path)
        
        assert result.n_skipped == 0
        assert len(result.resorts) == 2
        assert result.resorts[0].id == "resort_a"
        assert result.resorts[1].id == "resort_b"
