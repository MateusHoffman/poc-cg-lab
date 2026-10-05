import pytest

from app.sandbox import SandboxError, run_sandbox


def test_calculates_installment():
    value = run_sandbox("round(pmt(10000, 0.01, 12), 2)")
    assert value == pytest.approx(888.49, abs=0.01)


def test_blocks_import_and_attribute_access():
    with pytest.raises(SandboxError):
        run_sandbox("__import__('os').system('ls')")
    with pytest.raises(SandboxError):
        run_sandbox("(1).to_bytes(1, 'little')")
