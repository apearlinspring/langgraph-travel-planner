import json
from pathlib import Path

from scripts import render_storage_expansion_request as request


def _storage_readiness():
    return {
        "version": "storage_expansion_readiness.v1",
        "status": "blocked",
        "decision": "storage_expansion_required",
        "sections": {
            "disk_usage": {
                "root": {"used_percent": 97, "free_mb": 2287},
                "deploy": {"used_percent": 97, "free_mb": 2287},
                "docker_data_root": {"used_percent": 97, "free_mb": 2287},
            },
            "mount_sharing": {
                "root_deploy_same_mount": True,
                "root_docker_same_mount": True,
                "deploy_docker_same_mount": True,
            },
            "block_topology": {
                "disk_count": 1,
                "block_node_count": 2,
                "unmounted_block_count": 0,
                "largest_unmounted_mb": 0,
            },
            "restore_workspace": {
                "status": "blocked",
                "effective_free_mb": 2287,
                "required_free_mb": 4096,
                "gap_mb": 1809,
            },
            "recommendation": {
                "strategy": "expand_root_volume_or_attach_new_disk_for_docker_data",
                "min_additional_free_mb": 1809,
                "suggested_new_free_mb": 8192,
            },
        },
    }


def _post_cleanup():
    return {
        "version": "disk_remediation_post_cleanup.v1",
        "status": "blocked",
        "decision": "storage_expansion_required",
        "sections": {
            "capacity_delta": {
                "root_free_delta_mb": 21,
                "deploy_free_delta_mb": 21,
            },
            "execution": {
                "deleted": 2,
                "failed": 1,
            },
        },
    }


def _go_no_go():
    return {
        "version": "m1_go_no_go_evidence.v1",
        "status": "blocked",
        "decision": "no_go",
    }


def test_storage_expansion_request_summarizes_required_infra_change():
    report = request.build_storage_expansion_request(
        storage_readiness=_storage_readiness(),
        post_cleanup=_post_cleanup(),
        go_no_go=_go_no_go(),
    )

    assert report["status"] == "ready_for_infra_change"
    assert report["decision"] == "expand_root_volume_or_attach_new_disk_for_docker_data"
    assert report["policy"]["expands_disk"] is False
    assert report["capacity_evidence"]["cleanup_root_free_delta_mb"] == 21
    assert report["topology_evidence"]["unmounted_block_count"] == 0
    assert report["restore_workspace_requirement"]["gap_mb"] == 1809
    assert "collect_server_capacity_snapshot.py" in report["post_change_validation_commands"][0]


def test_storage_expansion_request_markdown_is_redacted():
    report = request.build_storage_expansion_request(
        storage_readiness=_storage_readiness(),
        post_cleanup=_post_cleanup(),
        go_no_go=_go_no_go(),
    )
    markdown = request.build_storage_expansion_request_markdown(report)

    assert "Storage Expansion Request" in markdown
    assert "root / Docker same mount" in markdown
    assert "Suggested post-change free space: `8192` MB" in markdown
    assert "203.0.113.10" not in markdown
    assert "D:\\Users\\Administrator" not in markdown
    assert "APPROVE_DOCKER_IMAGE_CLEANUP" not in markdown


def test_storage_expansion_request_cli_writes_without_echoing_source_paths(tmp_path: Path):
    storage_path = tmp_path / "storage.json"
    post_path = tmp_path / "post.json"
    go_path = tmp_path / "go.json"
    output_path = tmp_path / "storage-request.md"
    storage_path.write_text(json.dumps(_storage_readiness()), encoding="utf-8")
    post_path.write_text(json.dumps(_post_cleanup()), encoding="utf-8")
    go_path.write_text(json.dumps(_go_no_go()), encoding="utf-8")

    code = request.main(
        [
            "--storage-readiness-json",
            str(storage_path),
            "--post-cleanup-json",
            str(post_path),
            "--go-no-go-json",
            str(go_path),
            "--output",
            str(output_path),
        ]
    )
    payload = output_path.read_text(encoding="utf-8")

    assert code == 0
    assert "Storage Expansion Request" in payload
    assert str(storage_path) not in payload
    assert str(post_path) not in payload
    assert str(go_path) not in payload
