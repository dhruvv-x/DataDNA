import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from unittest.mock import patch, MagicMock
import pytest
from app.core.fabric_client import invoke, query, FabricError


def _mock_result(returncode=0, stdout="", stderr=""):
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


@patch("app.core.fabric_client.subprocess.run")
def test_invoke_success_returns_output(mock_run):
    mock_run.return_value = _mock_result(returncode=0, stdout="", stderr="Chaincode invoke successful. result: status:200")
    result = invoke("RegisterDatasetVersion", ["a", "1", "", "fp", "", "actor", "ts"])
    assert "status:200" in result


@patch("app.core.fabric_client.subprocess.run")
def test_invoke_failure_raises_fabric_error(mock_run):
    mock_run.return_value = _mock_result(returncode=1, stderr="connection refused")
    with pytest.raises(FabricError, match="connection refused"):
        invoke("RegisterDatasetVersion", ["a", "1", "", "fp", "", "actor", "ts"])


@patch("app.core.fabric_client.subprocess.run")
def test_query_success_returns_stdout(mock_run):
    mock_run.return_value = _mock_result(returncode=0, stdout="true")
    result = query("VerifyIntegrity", ["a", "1", "fp"])
    assert result == "true"


@patch("app.core.fabric_client.subprocess.run")
def test_query_failure_raises_fabric_error(mock_run):
    mock_run.return_value = _mock_result(returncode=1, stderr="chaincode not found")
    with pytest.raises(FabricError, match="chaincode not found"):
        query("VerifyIntegrity", ["a", "1", "fp"])
