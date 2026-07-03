import base64
import json
from pathlib import Path
from types import SimpleNamespace

from scripts import collect_storage_expansion_readiness as storage


def _b64_json(payload):
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def _parsed_without_unmounted_disk():
    return {
        "root_df": ["ext4|60347|2287|97"],
        "deploy_df": ["ext4|60347|2287|97"],
        "docker_root_df": ["ext4|60347|2287|97"],
        "root_mount_token": ["/"],
        "deploy_mount_token": ["/"],
        "docker_root_mount_token": ["/"],
        "lsblk_json_b64": [
            _b64_json(
                {
                    "blockdevices": [
                        {
                            "type": "disk",
                            "size": 64 * 1024 * 1024 * 1024,
                            "mountpoint": None,
                            "fstype": None,
                            "children": [
                                {
                                    "type": "part",
                                    "size": 64 * 1024 * 1024 * 1024,
                                    "mountpoint": "/",
                                    "fstype": "ext4",
                                }
                            ],
                        }
                    ]
                }
            )
        ],
        "docker_df_b64": [
            base64.b64encode(b"Images|643|4|150GB|140GB (93%)\n").decode("ascii")
        ],
    }


def _parsed_with_unmounted_disk():
    parsed = _parsed_without_unmounted_disk()
    parsed["lsblk_json_b64"] = [
        _b64_json(
            {
                "blockdevices": [
                    {
                        "type": "disk",
                        "size": 64 * 1024 * 1024 * 1024,
                        "mountpoint": None,
                        "children": [
                            {
                                "type": "part",
                                "size": 64 * 1024 * 1024 * 1024,
                                "mountpoint": "/",
                                "fstype": "ext4",
                            }
                        ],
                    },
                    {
                        "type": "disk",
                        "size": 20 * 1024 * 1024 * 1024,
                        "mountpoint": None,
                        "fstype": None,
                    },
                ]
            }
        )
    ]
    return parsed


def _parsed_with_old_lsblk_kv():
    parsed = _parsed_without_unmounted_disk()
    parsed.pop("lsblk_json_b64", None)
    kv = '\n'.join(
        [
            'TYPE="disk" SIZE="64424509440" MOUNTPOINT="" FSTYPE=""',
            'TYPE="part" SIZE="64423443968" MOUNTPOINT="/" FSTYPE="ext4"',
        ]
    )
    parsed["lsblk_kv_b64"] = [base64.b64encode(kv.encode("utf-8")).decode("ascii")]
    return parsed


def test_storage_expansion_recommends_root_or_new_disk_when_shared_mount_is_full():
    report = storage.build_storage_expansion_readiness_report_from_parsed(
        _parsed_without_unmounted_disk(),
        required_free_mb=4096,
    )

    assert report["status"] == "blocked"
    assert report["decision"] == "storage_expansion_required"
    assert report["sections"]["mount_sharing"]["root_docker_same_mount"] is True
    assert report["sections"]["block_topology"]["unmounted_block_count"] == 0
    assert report["sections"]["restore_workspace"]["gap_mb"] == 1809
    assert report["sections"]["recommendation"]["strategy"] == "expand_root_volume_or_attach_new_disk_for_docker_data"
    assert report["policy"]["device_names_echoed"] is False


def test_storage_expansion_old_lsblk_kv_does_not_treat_parent_disk_as_free():
    report = storage.build_storage_expansion_readiness_report_from_parsed(
        _parsed_with_old_lsblk_kv(),
        required_free_mb=4096,
    )

    assert report["sections"]["block_topology"]["status"] == "passed"
    assert report["sections"]["block_topology"]["disk_count"] == 1
    assert report["sections"]["block_topology"]["unmounted_block_count"] == 0
    assert report["sections"]["recommendation"]["strategy"] == "expand_root_volume_or_attach_new_disk_for_docker_data"


def test_storage_expansion_recommends_mounting_available_block_device():
    report = storage.build_storage_expansion_readiness_report_from_parsed(
        _parsed_with_unmounted_disk(),
        required_free_mb=4096,
    )

    assert report["sections"]["block_topology"]["unmounted_block_count"] == 1
    assert report["sections"]["recommendation"]["strategy"] == "mount_available_block_device"


def test_storage_expansion_markdown_redacts_private_values():
    report = storage.build_storage_expansion_readiness_report_from_parsed(
        _parsed_without_unmounted_disk(),
        required_free_mb=4096,
    )
    markdown = storage.build_storage_expansion_readiness_markdown(report)

    assert "Storage Expansion Readiness" in markdown
    assert "Root / Docker same mount" in markdown
    assert "203.0.113.10" not in markdown
    assert "D:\\Users\\Administrator" not in markdown


def test_storage_expansion_cli_writes_redacted_report(monkeypatch, tmp_path: Path):
    stdout = "\n".join(
        f"__ZHIXING_STORAGE__{key}={values[0]}"
        for key, values in _parsed_without_unmounted_disk().items()
    )

    def fake_run(args, *, input_text=None, timeout_seconds=90):
        return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr(storage, "_run_command", fake_run)
    output = tmp_path / "storage.json"

    code = storage.main(
        [
            "--ssh-target",
            "root@203.0.113.10",
            "--deploy-dir",
            "/opt/example",
            "--output",
            str(output),
        ]
    )
    payload = output.read_text(encoding="utf-8")
    data = json.loads(payload)

    assert code == 2
    assert data["target"]["ssh_target"] == "<server-target>"
    assert data["target"]["deploy_dir"] == "<deploy-dir>"
    assert "203.0.113.10" not in payload
    assert "/opt/example" not in payload
