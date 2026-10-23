"""Contract checks for synthetic strategy API examples and the opt-in demo."""

from __future__ import annotations

import json
import importlib.util
import io
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

from src.v2_contracts import (
    validate_fact_check_result,
    validate_strategy,
    validate_task_context,
)
from src.final_content_contracts import content_digest, validate_final_content


ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = ROOT / "docs" / "examples"
SYNTHETIC_FACT_ID = "fact-synthetic-001"


def read_example(name: str) -> dict:
    with (EXAMPLES / name).open(encoding="utf-8") as source:
        return json.load(source)


class StrategyExampleTests(unittest.TestCase):
    def load_demo(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "strategy_http_demo.py"
        spec = importlib.util.spec_from_file_location("strategy_http_demo_offline", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_strategy_http_wait_covers_bounded_workflow_without_changing_other_routes(self):
        module = self.load_demo()
        with patch.dict(os.environ, {"STRATEGY_LLM_TIMEOUT_SECONDS": "120"}):
            self.assertEqual(module.http_timeout("/api/strategy/generate"), 1500)
            self.assertEqual(module.http_timeout("/api/agent/understand"), 240)
            self.assertEqual(module.http_timeout("/api/facts/check"), 240)
            self.assertEqual(module.http_timeout("/api/facts/check-final"), 1200)
            connection = Mock()
            connection.getresponse.return_value.status = 502
            connection.getresponse.return_value.read.return_value = b'{"success": false}'
            with patch.object(module.http.client, "HTTPConnection", return_value=connection) as constructor, patch("sys.stdout", io.StringIO()):
                module.post(12345, "/api/strategy/generate", {"task_id": "fixture", "expected_revision": 5})
            constructor.assert_called_once_with("127.0.0.1", 12345, timeout=1500)

    def test_failed_demo_preserves_server_and_current_task_until_explicit_interrupt(self):
        module = self.load_demo()
        server, thread, events = Mock(), Mock(), []
        server.server_port = 12345
        server.shutdown.side_effect = lambda: events.append("shutdown")
        server.server_close.side_effect = lambda: events.append("close")
        thread.is_alive.return_value = True
        def join(timeout):
            events.append("wait" if timeout == 30 else "join")
            if timeout == 30:
                raise KeyboardInterrupt
        thread.join.side_effect = join
        with patch.object(module, "output") as output, patch("sys.stdout", io.StringIO()):
            module.finish_server(server, thread, keep=True,
                                 task={"task_id": "actual-fixture", "revision": 5}, failure_stage="strategy/generate")
        self.assertEqual(events, ["wait", "shutdown", "close", "join"])
        self.assertEqual(output.call_args.args[0]["task_id"], "actual-fixture")
        self.assertEqual(output.call_args.args[0]["revision"], 5)
        self.assertTrue(output.call_args.args[0]["server_retained"])

    def test_successful_demo_shuts_down_without_waiting(self):
        module = self.load_demo()
        server, thread = Mock(), Mock()
        with patch("sys.stdout", io.StringIO()):
            module.finish_server(server, thread, keep=False, task={}, failure_stage="")
        thread.is_alive.assert_not_called()
        server.shutdown.assert_called_once()
        server.server_close.assert_called_once()

    def test_demo_report_preserves_unicode_on_windows_legacy_console(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "strategy_http_demo.py"
        spec = importlib.util.spec_from_file_location("strategy_http_demo_offline", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        data = {"claim": "真实资料中的 Unicode\\u2060 与 emoji 😀".replace("\\u2060", "\u2060")}
        buffer = io.BytesIO()
        console = io.TextIOWrapper(buffer, encoding="gbk")
        try:
            with patch("sys.stdout", console):
                module.output(data)
            console.flush()
            self.assertEqual(json.loads(buffer.getvalue().decode("gbk")), data)
        finally:
            console.close()

    def test_strategy_generate_and_confirm_examples_match_runtime_contracts(self):
        generated = read_example("strategy-generate-response.json")
        data = generated["data"]
        task = validate_task_context(data["task"])
        strategy = validate_strategy(data["strategy"], {SYNTHETIC_FACT_ID})
        self.assertTrue(generated["success"])
        self.assertEqual(task["workflow_status"], "awaiting_user_confirmation")
        self.assertEqual(strategy["confirmation_status"], "pending")
        self.assertEqual(strategy["task_id"], task["task_id"])
        self.assertEqual(strategy["task_revision"] + 1, task["revision"])
        self.assertEqual(strategy["cta"], "")
        self.assertEqual(set(strategy["fact_references"]), {SYNTHETIC_FACT_ID})
        for result in data["fact_check"]["results"]:
            validate_fact_check_result(result)
            self.assertEqual(result["status"], "supported")
            self.assertEqual(result["task_revision"], strategy["task_revision"])

        confirmed = read_example("strategy-confirm-response.json")
        confirmed_task = validate_task_context(confirmed["data"]["task"])
        confirmed_strategy = validate_strategy(
            confirmed["data"]["strategy"], {SYNTHETIC_FACT_ID}
        )
        self.assertEqual(confirmed_task["workflow_status"], "strategy_confirmed")
        self.assertEqual(confirmed_strategy["confirmation_status"], "confirmed")
        self.assertEqual(confirmed_strategy["confirmed_at_task_revision"], confirmed_task["revision"])
        self.assertEqual(confirmed_strategy["strategy_id"], strategy["strategy_id"])
        self.assertEqual(confirmed_strategy["strategy_version"], strategy["strategy_version"])

    def test_final_check_examples_bind_exact_content_current_strategy_and_text_only_pass(self):
        request = read_example("final-check-request.json")
        response = read_example("final-check-response.json")
        draft = validate_final_content(request["content"])
        task = validate_task_context(response["data"]["task"])
        checked = response["data"]["final_check"]
        self.assertEqual(set(request), {"task_id", "expected_revision", "strategy_id", "strategy_version", "content"})
        self.assertEqual(checked["task_id"], request["task_id"])
        self.assertEqual(checked["strategy_id"], request["strategy_id"])
        self.assertEqual(checked["strategy_version"], request["strategy_version"])
        self.assertEqual(checked["content_digest"], content_digest(draft))
        self.assertEqual(checked["task_revision"], request["expected_revision"] + 1)
        self.assertEqual(checked["saved_task_revision"], task["revision"])
        self.assertEqual(checked["text_check"]["status"], "passed")
        self.assertEqual(checked["usable_text"]["plain_text"], draft["plain_text"])
        self.assertEqual(checked["image_check"]["status"], "unknown")
        self.assertFalse(checked["image_check"]["visual_check_performed"])
        self.assertFalse(checked["overall"]["ready_to_publish"])
        self.assertFalse(checked["overall"]["completed"])
        self.assertEqual(checked["overall"]["status"], "partial")
        for item in checked["text_check"]["results"]:
            validate_fact_check_result(item["check"])

    def test_final_acceptance_demo_preserves_conditions_and_adds_unreferenced_bad_claims(self):
        module = self.load_demo()
        original_handoff = {
            "strategy": {"topic": "测试主题"},
            "fact_records": [{"fact_id": "F1", "claim": "处理器频率：3.2 GHz，仅适用测试配置。"}],
        }
        good, bad, numeric_changed = module.acceptance_content(original_handoff)
        self.assertEqual(good["body"], original_handoff["fact_records"][0]["claim"])
        self.assertEqual(good["plain_text"], good["body"])
        self.assertEqual(good["fact_references"], ["F1"])
        self.assertEqual(good["images"], [])
        self.assertTrue(numeric_changed)
        self.assertIn("999 GHz，仅适用测试配置", bad["body"])
        self.assertIn("4999 元", bad["body"])
        self.assertEqual(bad["fact_references"], [])
        validate_final_content(good)
        validate_final_content(bad)
        self.assertNotEqual(content_digest(good), content_digest(bad))

    def test_handoff_contains_only_strategy_adopted_supported_facts_and_unknown_images(self):
        envelope = read_example("creative-handoff.json")
        handoff = envelope["data"]["handoff"]
        task = validate_task_context(handoff["task"])
        strategy = validate_strategy(handoff["strategy"], {SYNTHETIC_FACT_ID})
        self.assertTrue(envelope["success"])
        self.assertEqual(task["workflow_status"], "strategy_confirmed")
        self.assertEqual(strategy["confirmation_status"], "confirmed")
        self.assertEqual({item["fact_id"] for item in handoff["fact_records"]},
                         set(strategy["fact_references"]))
        self.assertTrue(all(item["status"] == "supported" for item in handoff["fact_records"]))
        self.assertEqual(handoff["image_status"], "unknown")
        self.assertEqual(handoff["images"], [])
        self.assertEqual(handoff["knowledge_source"]["live"], False)
        self.assertEqual(handoff["knowledge_source"]["mode"], "local")

    def test_strategy_demo_requires_explicit_live_flag_before_starting(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "strategy_http_demo.py"
        result = subprocess.run(
            [sys.executable, str(script)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        output = result.stdout + result.stderr
        self.assertEqual(result.returncode, 2)
        self.assertIn("require --live", output)
        self.assertNotIn("fresh_loopback_server_started", output)

    def test_final_check_demo_also_requires_explicit_live_authorization(self):
        script = Path(__file__).resolve().parents[1] / "scripts" / "strategy_http_demo.py"
        result = subprocess.run([sys.executable, "-B", str(script), "--check-final"], cwd=ROOT,
                                capture_output=True, text=True, timeout=10, check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("require --live", result.stderr)
        self.assertNotIn("fresh_loopback_server_started", result.stdout)


if __name__ == "__main__":
    unittest.main()
