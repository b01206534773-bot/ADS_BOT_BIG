import asyncio
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import bm_card_service


def test_ensure_playwright_browser_installs_chromium_when_missing(monkeypatch):
    calls = []
    probe_calls = 0

    def fake_probe_playwright_browser():
        nonlocal probe_calls
        probe_calls += 1
        return probe_calls > 1

    def fake_run(cmd, capture_output, text, check):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(bm_card_service, "_probe_playwright_browser", fake_probe_playwright_browser)
    monkeypatch.setattr(bm_card_service.subprocess, "run", fake_run)
    monkeypatch.setattr(bm_card_service.sys, "executable", "/usr/bin/python3")

    assert bm_card_service._ensure_playwright_browser() is True
    assert calls == [["/usr/bin/python3", "-m", "playwright", "install", "chromium"]]
