from pathlib import Path

from scripts import render_server_env_checklist as checklist


def test_server_env_checklist_uses_env_example_names_without_values(tmp_path: Path):
    env_example = tmp_path / ".env.example"
    env_example.write_text(
        "\n".join(
            [
                "APP_ENV=development",
                "DASHSCOPE_API_KEY=real-looking-value-that-must-not-appear",
                "POSTGRES_PASSWORD=another-real-looking-value",
                "ZHIXING_PUBLIC_BASE_URL=http://127.0.0.1:8000",
            ]
        ),
        encoding="utf-8",
    )

    report = checklist.build_server_env_checklist_report(env_example_path=env_example)
    payload = str(report)

    assert report["version"] == "server_env_checklist.v1"
    assert report["policy"]["reads_dotenv"] is False
    assert report["policy"]["reads_current_process_environment"] is False
    assert report["policy"]["does_not_echo_values"] is True
    assert "real-looking-value-that-must-not-appear" not in payload
    assert "another-real-looking-value" not in payload
    assert any(item["env_var"] == "DASHSCOPE_API_KEY" for item in report["env_vars"])
    assert any(item["env_var"] == "ZHIXING_PUBLIC_BASE_URL" for item in report["env_vars"])


def test_server_env_checklist_marks_required_secret_and_non_secret_inputs():
    report = checklist.build_server_env_checklist_report()
    by_name = {item["env_var"]: item for item in report["env_vars"]}

    assert by_name["DASHSCOPE_API_KEY"]["secret"] is True
    assert by_name["DASHSCOPE_API_KEY"]["required_for_m1"] is True
    assert by_name["DASHSCOPE_API_KEY"]["placeholder"] == "<set-in-secret-store>"
    assert by_name["ZHIXING_M1_AUDIENCE"]["secret"] is False
    assert by_name["ZHIXING_M1_AUDIENCE"]["required_for_m1"] is True
    assert by_name["APP_ENV"]["placeholder"] == "staging"
    assert report["target_file"] == "<deploy-dir>/shared/.env"
    assert "chmod 600" in report["file_permission"]


def test_server_env_checklist_markdown_contains_operator_steps():
    report = checklist.build_server_env_checklist_report()

    markdown = checklist.build_server_env_checklist_markdown(report)

    assert "Server Env Checklist" in markdown
    assert "<deploy-dir>/shared/.env" in markdown
    assert "DASHSCOPE_API_KEY" in markdown
    assert "chmod 600" in markdown
    assert "check_server_env_file.py" in markdown
    assert "does_not_echo_values" in markdown


def test_server_env_template_uses_only_placeholders():
    report = checklist.build_server_env_checklist_report()

    template = checklist.build_server_env_template_text(report)

    assert "ZhiXing server .env template" in template
    assert "Do not commit real values" in template
    assert "DASHSCOPE_API_KEY=<set-in-secret-store>" in template
    assert "APP_ENV=staging" in template
    assert "your-dashscope-api-key" not in template
    assert "change-me" not in template


def test_server_env_checklist_cli_writes_markdown(tmp_path: Path):
    output = tmp_path / "server-env.md"

    code = checklist.main(["--output", str(output)])

    assert code == 0
    content = output.read_text(encoding="utf-8")
    assert "Server Env Checklist" in content
    assert "ZHIXING_PUBLIC_BASE_URL" in content
