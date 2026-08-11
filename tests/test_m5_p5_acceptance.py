from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from xuanyi_npc.evaluation import m5_acceptance
from xuanyi_npc.evaluation.m5_acceptance import (
    HistoricalEvidence,
    M5AcceptanceResult,
    P4B_RAW_SHA256,
    P4D_RAW_SHA256,
    run_acceptance,
)
from xuanyi_npc.storage import JsonStateStore


ROOT = Path(__file__).parents[1]
RESOURCE_ROOT = ROOT / "src" / "xuanyi_npc" / "resources"
CASE_DIR = RESOURCE_ROOT / "cases"
CAMPAIGN_RULES = RESOURCE_ROOT / "campaign" / "cross_episode_rules_v1.json"


def historical_evidence() -> HistoricalEvidence:
    return HistoricalEvidence(
        p4b_raw_sha256=P4B_RAW_SHA256,
        p4d_raw_sha256=P4D_RAW_SHA256,
    )


def clean_environment() -> dict[str, str]:
    env = os.environ.copy()
    for name in tuple(env):
        if "DEEPSEEK" in name.upper() or "API_KEY" in name.upper():
            env.pop(name, None)
    env["HF_HUB_OFFLINE"] = "1"
    env["TRANSFORMERS_OFFLINE"] = "1"
    return env


def test_acceptance_contract_is_strict() -> None:
    with pytest.raises(ValidationError):
        HistoricalEvidence.model_validate(
            {
                "p4b_raw_sha256": P4B_RAW_SHA256,
                "p4d_raw_sha256": P4D_RAW_SHA256,
                "unknown": True,
            }
        )
    with pytest.raises(ValidationError):
        M5AcceptanceResult.model_validate({"schema_version": "other"})


def test_full_acceptance_runs_public_fake_path_across_real_processes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(
        m5_acceptance,
        "_verify_history",
        lambda _p4b, _p4d: historical_evidence(),
    )
    result = run_acceptance(
        run_id="m5_acceptance_test",
        case_dir=CASE_DIR,
        state_dir=state,
        campaign_rules=CAMPAIGN_RULES,
        p4b_result=tmp_path / "unused_p4b.json",
        p4d_result=tmp_path / "unused_p4d.json",
    )

    assert result.status == "passed"
    assert [item.case_id for item in result.primary_cases] == [
        "old_paper_umbrella",
        "gray_hearth_inn",
        "moon_well_echo",
    ]
    assert all(item.event_sequences == tuple(range(1, 9)) for item in result.primary_cases)
    assert all(item.score == 100 and item.replay_matches_disk for item in result.primary_cases)
    assert result.primary_campaign_event_sequences == (1, 2, 3)
    assert result.primary_knowledge_ids == {
        "contract_provenance_check",
        "handoff_sequence_check",
    }
    assert result.secondary_used_neutral_opening
    assert result.players_isolated
    assert result.worker_processes == 32
    assert result.rejection_evidence.zero_event_count == 4
    assert result.rejection_evidence.zero_revision_count == 4
    assert result.rejection_evidence.byte_identical_count == 4
    assert result.shadow_evidence.request_bytes_equal
    assert result.external_use.network_requests == 0
    serialized = result.model_dump_json()
    for forbidden in (
        "root_cause",
        "valid_diagnosis_ids",
        "diagnosis_correct",
        "DEEPSEEK_API_KEY",
        "Authorization",
        "retrieved_memories",
    ):
        assert forbidden not in serialized


def test_readme_manual_cli_flow_recovers_in_second_process(tmp_path: Path) -> None:
    state = tmp_path / "play"
    state.mkdir()
    command = [
        sys.executable,
        "-m",
        "xuanyi_npc.cli.play",
        "--case-dir",
        str(CASE_DIR),
        "--state-dir",
        str(state),
        "--mode",
        "manual",
        "--semantic-shadow",
        "off",
    ]
    first = subprocess.run(
        command,
        input="1\n验收玩家\n1\n1\n1\n99\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
        env=clean_environment(),
    )
    assert first.returncode == 0, first.stderr
    assert "灰灶客栈与无火炊烟" in first.stdout
    assert "月井回声与错投木简" in first.stdout
    assert "旧纸伞与失约书生" in first.stdout
    assert "会话修订：0" in first.stdout
    sessions = JsonStateStore(state).list_case_sessions()
    assert len(sessions) == 1 and sessions[0].revision == 1
    session_id = sessions[0].session_id

    second = subprocess.run(
        command,
        input="2\n1\n1\n1\n99\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
        env=clean_environment(),
    )
    assert second.returncode == 0, second.stderr
    assert "已恢复未完成病例" in second.stdout
    assert "会话修订：1" in second.stdout
    restored = JsonStateStore(state).list_case_sessions()
    assert len(restored) == 1
    assert restored[0].session_id == session_id
    assert restored[0].revision == 1
    assert first.stderr == second.stderr == ""


def test_module_import_has_no_file_model_or_network_side_effect(tmp_path: Path) -> None:
    script = (
        "import sys; import xuanyi_npc.evaluation.m5_acceptance; "
        "assert 'torch' not in sys.modules; "
        "assert 'sentence_transformers' not in sys.modules"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
        env=clean_environment(),
    )
    assert completed.returncode == 0, completed.stderr
    assert tuple(tmp_path.iterdir()) == ()


def test_history_sha_constants_match_ignored_raw_results_when_available() -> None:
    p4b = ROOT / "results" / "m5_p4b_campaign_20260811.json"
    p4d = ROOT / "results" / "m5_p4d_recovery_20260811.json"
    if not p4b.is_file() or not p4d.is_file():
        pytest.skip("ignored paid-run evidence is intentionally not required in fresh clones")
    evidence = m5_acceptance._verify_history(p4b, p4d)
    assert evidence.verification_mode == "raw_sha256_verified"
    assert evidence.p4b_raw_sha256 == P4B_RAW_SHA256
    assert evidence.p4d_raw_sha256 == P4D_RAW_SHA256


def test_fresh_install_can_verify_history_from_public_package_manifest() -> None:
    evidence = m5_acceptance._verify_history(None, None)
    assert evidence.verification_mode == "public_manifest"
    assert evidence.p4b_raw_sha256 == P4B_RAW_SHA256
    assert evidence.p4d_raw_sha256 == P4D_RAW_SHA256


def test_acceptance_result_json_uses_only_sanitized_public_evidence(
    tmp_path: Path,
) -> None:
    payload = historical_evidence().model_dump(mode="json")
    output = tmp_path / "sample.json"
    output.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    text = output.read_text(encoding="utf-8")
    assert str(tmp_path.resolve()) not in text
    assert "provider_request_id" not in text
