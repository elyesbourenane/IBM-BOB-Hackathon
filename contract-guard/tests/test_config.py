"""Tests for the contractguard.yaml config loader."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from contract_guard.config import load_config


def _write_config(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "contractguard.yaml"
    p.write_text(textwrap.dedent(content).lstrip("\n"), encoding="utf-8")
    return p


class TestLoadConfig:
    def test_parses_valid_config(self, tmp_path):
        # Create stub contract files so paths exist (load_config only resolves, not opens)
        (tmp_path / "contracts").mkdir()
        (tmp_path / "contracts" / "payment-service.yaml").write_text("", encoding="utf-8")
        producer_dir = tmp_path / "payment-service" / "docs"
        producer_dir.mkdir(parents=True)
        (producer_dir / "openapi.yaml").write_text("", encoding="utf-8")

        config_path = _write_config(
            tmp_path,
            f"""
            service: payment-client
            dependencies:
              - service: payment-service
                consumer_contract: contracts/payment-service.yaml
                producer_contract: payment-service/docs/openapi.yaml
            """,
        )

        config = load_config(config_path)
        assert config.service == "payment-client"
        assert len(config.dependencies) == 1
        dep = config.dependencies[0]
        assert dep.service == "payment-service"
        assert dep.consumer_contract == (tmp_path / "contracts" / "payment-service.yaml").resolve()
        assert dep.producer_contract == (tmp_path / "payment-service" / "docs" / "openapi.yaml").resolve()
        assert config.base_dir == tmp_path.resolve()

    def test_paths_resolved_relative_to_config_dir(self, tmp_path):
        subdir = tmp_path / "repos" / "client"
        subdir.mkdir(parents=True)
        config_path = subdir / "contractguard.yaml"
        config_path.write_text(
            textwrap.dedent("""
            service: my-client
            dependencies:
              - service: my-service
                consumer_contract: consumer.yaml
                producer_contract: ../my-service/api.yaml
            """).lstrip("\n"),
            encoding="utf-8",
        )

        config = load_config(config_path)
        dep = config.dependencies[0]
        assert dep.consumer_contract == (subdir / "consumer.yaml").resolve()
        assert dep.producer_contract == (subdir / "../my-service/api.yaml").resolve()

    def test_missing_service_raises(self, tmp_path):
        cfg = _write_config(tmp_path, "dependencies: []\n")
        with pytest.raises(ValueError, match="missing required field 'service'"):
            load_config(cfg)

    def test_missing_consumer_contract_raises(self, tmp_path):
        cfg = _write_config(
            tmp_path,
            """
            service: client
            dependencies:
              - service: api
                producer_contract: ../api/openapi.yaml
            """,
        )
        with pytest.raises(ValueError, match="missing required field 'consumer_contract'"):
            load_config(cfg)

    def test_missing_producer_contract_raises(self, tmp_path):
        cfg = _write_config(
            tmp_path,
            """
            service: client
            dependencies:
              - service: api
                consumer_contract: contracts/api.yaml
            """,
        )
        with pytest.raises(ValueError, match="missing required field 'producer_contract'"):
            load_config(cfg)

    def test_file_not_found_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nonexistent.yaml")

    def test_not_a_mapping_raises(self, tmp_path):
        cfg = tmp_path / "contractguard.yaml"
        cfg.write_text("- item1\n- item2\n", encoding="utf-8")
        with pytest.raises(ValueError, match="must be a YAML mapping"):
            load_config(cfg)

    def test_empty_dependencies(self, tmp_path):
        cfg = _write_config(tmp_path, "service: my-service\n")
        config = load_config(cfg)
        assert config.service == "my-service"
        assert config.dependencies == []
