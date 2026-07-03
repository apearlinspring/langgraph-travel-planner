from pathlib import Path

from scripts import check_m1_public_release_closure as closure


def _passed_public_boundary(**_kwargs):
    return {
        "version": "public_release_boundary.v1",
        "status": "passed",
        "candidate_count": 10,
        "scanned_count": 8,
        "forbidden_paths": [],
        "content_findings": [],
    }


def _write_required_tree(root: Path) -> None:
    generic_doc = "Public M1 deployment document.\n"
    doc_overrides = {
        "docs/部署与运行/m1-controlled-trial-status.md": (
            "不能声明为完整生产就绪\n"
            "不接真实支付\n"
            "chat 小流量并发采样\n"
            "独立补充 workflow/signoff\n"
        ),
        "docs/部署与运行/m1-operations-evidence-playbook.md": (
            "不把项目包装成完整生产高可用系统\n"
            "不触发真实支付\n"
            "独立 workflow/signoff\n"
        ),
        "docs/部署与运行/deployment-readiness.md": (
            "Real production hostnames, IP addresses, SSH users, private keys, `.env` files and database contents must stay outside Git.\n"
            "check_public_release_boundary.py\n"
        ),
        "docs/部署与运行/security-release-key-rotation-runbook.md": (
            "不记录真实密钥\n"
            "check_public_release_boundary.py\n"
        ),
    }
    for relative_path in closure.REQUIRED_PUBLIC_DOCS:
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(doc_overrides.get(relative_path, generic_doc), encoding="utf-8")
    for relative_path in closure.REQUIRED_PUBLIC_SCRIPTS:
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# public script placeholder\n", encoding="utf-8")


def test_m1_public_release_closure_passes_complete_public_package(tmp_path: Path):
    _write_required_tree(tmp_path)

    report = closure.build_m1_public_release_closure_report(
        repo_root=tmp_path,
        public_boundary_builder=_passed_public_boundary,
    )

    assert report["status"] == "passed"
    assert report["section_statuses"]["required_public_docs"] == "passed"
    assert report["section_statuses"]["required_public_scripts"] == "passed"
    assert report["section_statuses"]["claim_boundary"] == "passed"
    assert report["section_statuses"]["public_coordinate_scan"] == "passed"
    assert report["policy"]["reads_dotenv"] is False
    assert report["policy"]["connects_ssh"] is False


def test_m1_public_release_closure_blocks_missing_required_doc(tmp_path: Path):
    _write_required_tree(tmp_path)
    (tmp_path / "docs/部署与运行/m1-launch-checklist.md").unlink()

    report = closure.build_m1_public_release_closure_report(
        repo_root=tmp_path,
        public_boundary_builder=_passed_public_boundary,
    )

    assert report["status"] == "blocked"
    docs = report["sections"]["required_public_docs"]
    assert docs["status"] == "blocked"
    assert "docs/部署与运行/m1-launch-checklist.md" in docs["missing"]


def test_m1_public_release_closure_blocks_missing_claim_boundary_phrase(tmp_path: Path):
    _write_required_tree(tmp_path)
    (tmp_path / "docs/部署与运行/m1-controlled-trial-status.md").write_text(
        "不能声明为完整生产就绪\n不接真实支付\nchat 小流量并发采样\n",
        encoding="utf-8",
    )

    report = closure.build_m1_public_release_closure_report(
        repo_root=tmp_path,
        public_boundary_builder=_passed_public_boundary,
    )

    assert report["status"] == "blocked"
    claim_boundary = report["sections"]["claim_boundary"]
    assert claim_boundary["status"] == "blocked"
    assert any(
        "独立补充 workflow/signoff" in item["missing_phrases"]
        for item in claim_boundary["items"]
    )


def test_m1_public_release_closure_blocks_real_public_coordinates(tmp_path: Path):
    _write_required_tree(tmp_path)
    extra_doc = tmp_path / "docs/部署与运行/private-leak.md"
    forbidden_url = "https://" + ".".join(("travel", "403edr", "cn")) + "/"
    extra_doc.write_text(f"Do not publish {forbidden_url} here.\n", encoding="utf-8")

    report = closure.build_m1_public_release_closure_report(
        repo_root=tmp_path,
        public_boundary_builder=_passed_public_boundary,
    )

    assert report["status"] == "blocked"
    coordinate_scan = report["sections"]["public_coordinate_scan"]
    assert coordinate_scan["status"] == "blocked"
    assert coordinate_scan["findings"][0]["kind"] == "real_domain"


def test_m1_public_release_closure_blocks_public_boundary_failure(tmp_path: Path):
    _write_required_tree(tmp_path)

    def blocked_public_boundary(**_kwargs):
        return {
            "version": "public_release_boundary.v1",
            "status": "blocked",
            "forbidden_paths": [".env"],
            "content_findings": [],
        }

    report = closure.build_m1_public_release_closure_report(
        repo_root=tmp_path,
        public_boundary_builder=blocked_public_boundary,
    )

    assert report["status"] == "blocked"
    assert report["section_statuses"]["public_release_boundary"] == "blocked"
