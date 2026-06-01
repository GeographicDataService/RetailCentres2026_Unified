from pathlib import Path

from rc_id_lookup_build import build_rcid_lookup
from rc_lookup import build_rc_lookups
from rc_foursquare_anchors import build_foursquare_anchor_counts
from rc_classification import run_classification
from rc_classification_ldc_numbers_comparison import run_ldc_numbers_comparison


def _load_json(path: Path) -> dict:
    import json

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _load_yaml(path: Path) -> dict:
    try:
        import yaml  # type: ignore
    except ImportError as exc:
        raise ImportError(
            "PyYAML is required to load config.yaml. "
            "Install with: pip install pyyaml"
        ) from exc

    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_config(path: str | None = None) -> dict:
    if path:
        config_path = Path(path)
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        if config_path.suffix in {".yaml", ".yml"}:
            return _load_yaml(config_path)
        return _load_json(config_path)

    yaml_path = Path("config.yaml")
    if yaml_path.exists():
        return _load_yaml(yaml_path)

    json_path = Path("config.json")
    if json_path.exists():
        return _load_json(json_path)

    raise FileNotFoundError("No config.yaml or config.json found.")


def main() -> None:
    cfg = load_config()

    build_rcid_lookup(**cfg["rc_id_lookup"])
    print("---1. RC_ID lookup between old and new RC_ID built.")
    build_rc_lookups(**cfg["rc_lookup"])
    build_foursquare_anchor_counts(**cfg["rc_foursquare_anchors"])

    run_classification(**cfg["rc_classification"])
    run_ldc_numbers_comparison(**cfg["rc_classification_ldc_numbers_comparison"])


if __name__ == "__main__":
    main()
