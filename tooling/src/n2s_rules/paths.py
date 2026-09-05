from pathlib import Path


def default_n2s_root():
    return Path(__file__).resolve().parents[3]


def default_rules_root():
    return default_n2s_root() / "rules"
