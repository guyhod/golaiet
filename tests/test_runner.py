from decimal import Decimal

from agent import runner


def test_build_cmd_puts_prompt_before_variadic_flags():
    cmd = runner.build_cmd("hello", claude_bin="claude", model="sonnet", system_prompt="sys", resume="not-a-uuid",
                           mcp_config_path="/tmp/m.json", allowed_tools=["mcp__golaiet__*", "WebSearch"], tools=["WebSearch"])
    assert cmd[:5] == ["claude", "--print", "--output-format", "json", "--model"]
    assert "--resume" not in cmd                       # a non-UUID resume is ignored
    assert cmd[cmd.index("--mcp-config") + 2] == "--strict-mcp-config"
    assert cmd.index("hello") < cmd.index("--allowedTools") < cmd.index("--tools")
    assert "--safe-mode" not in cmd and "--bare" not in cmd


def test_build_cmd_resumes_a_real_uuid():
    cmd = runner.build_cmd("hi", claude_bin="claude", model="sonnet", resume="890a0738-839e-4570-9cdd-2a0e1388877c")
    assert cmd[cmd.index("--resume") + 1] == "890a0738-839e-4570-9cdd-2a0e1388877c"


def test_parse_envelope_reads_result_session_and_cost():
    result = runner.parse_envelope('{"result":"SUM=42","session_id":"abc","total_cost_usd":0.0301,"is_error":false}')
    assert result.text == "SUM=42" and result.session_id == "abc" and result.cost_usd == Decimal("0.0301")
    assert not result.is_error and result.cost_usd is not None


def test_parse_envelope_without_json_keeps_text_and_exit_code():
    result = runner.parse_envelope("Error: something broke", exit_code=1)
    assert result.text == "Error: something broke" and result.is_error and result.cost_usd is None


def test_billing_markers():
    assert runner.parse_envelope('{"result":"You have hit your session limit · resets 10:50pm"}').is_billing_abort
    assert not runner.parse_envelope('{"result":"Filed 3 observations."}').is_billing_abort
