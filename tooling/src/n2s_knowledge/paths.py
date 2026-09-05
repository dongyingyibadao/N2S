from pathlib import Path


def default_n2s_root():
    return Path(__file__).resolve().parents[3]
