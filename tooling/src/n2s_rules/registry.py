import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import jsonschema
import yaml

from .plugins import PluginError, load_rule_plugins


class RegistryError(RuntimeError):
    pass


@dataclass(frozen=True)
class RulePackage:
    package: Path
    manifest_path: Path
    manifest: dict


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _package_sha256(rule):
    manifest = rule.manifest
    relative_paths = {
        "manifest.yaml", "README.md", "fixtures/before.py", "fixtures/after.py", "fixtures/no_match.py",
        manifest["automation"]["detector"], manifest["automation"]["codemod"], manifest["automation"]["validator"],
        *manifest["evidence"],
    }
    digest = hashlib.sha256()
    for relative in sorted(relative_paths):
        path = rule.package / relative
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RegistryError(f"cannot read JSON {path}: {error}") from error


def _validate(instance, schema_path, label):
    schema = _read_json(schema_path)
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    errors = sorted(validator.iter_errors(instance), key=lambda error: list(error.absolute_path))
    if errors:
        details = "; ".join(f"{'/'.join(map(str, error.absolute_path)) or '<root>'}: {error.message}" for error in errors)
        raise RegistryError(f"{label} schema validation failed: {details}")


def discover_rules(rules_root):
    rules_root = Path(rules_root).resolve()
    schema_path = rules_root / "schema" / "rule.schema.json"
    packages = []
    seen = set()
    for manifest_path in sorted(rules_root.glob("*/manifest.yaml")):
        try:
            manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as error:
            raise RegistryError(f"cannot read manifest {manifest_path}: {error}") from error
        if not isinstance(manifest, dict):
            raise RegistryError(f"manifest must be an object: {manifest_path}")
        _validate(manifest, schema_path, str(manifest_path))
        rule_id = manifest["id"]
        if rule_id in seen:
            raise RegistryError(f"duplicate rule id: {rule_id}")
        if manifest_path.parent.name != rule_id:
            raise RegistryError(f"package directory must equal rule id: {manifest_path.parent.name} != {rule_id}")
        seen.add(rule_id)
        package = manifest_path.parent
        for required in ("README.md", "fixtures/before.py", "fixtures/after.py", "fixtures/no_match.py"):
            if not (package / required).is_file():
                raise RegistryError(f"missing required rule file: {package / required}")
        for evidence in manifest["evidence"]:
            if not (package / evidence).is_file():
                raise RegistryError(f"missing evidence file: {package / evidence}")
        packages.append(RulePackage(package=package, manifest_path=manifest_path, manifest=manifest))
    if not packages:
        raise RegistryError(f"no rule packages found under {rules_root}")
    return packages


def build_registry(rules_root, packages=None):
    rules_root = Path(rules_root).resolve()
    packages = packages or discover_rules(rules_root)
    entries = []
    for rule in sorted(packages, key=lambda item: item.manifest["id"]):
        manifest = rule.manifest
        entries.append(
            {
                "id": manifest["id"],
                "version": manifest["version"],
                "title": manifest["title"],
                "status": manifest["status"],
                "classification": manifest["classification"],
                "risk": manifest["risk"],
                "summary": manifest["summary"],
                "package": rule.package.relative_to(rules_root).as_posix(),
                "manifest_sha256": _sha256(rule.manifest_path),
                "package_sha256": _package_sha256(rule),
            }
        )
    return {
        "schema_version": "1.0.0",
        "generated_from": "rules/*/manifest.yaml",
        "approved_rule_count": sum(entry["status"] == "approved" for entry in entries),
        "rules": entries,
    }


def _validate_fixtures(rule):
    try:
        plugins = load_rule_plugins(rule.package, rule.manifest)
    except PluginError as error:
        raise RegistryError(str(error)) from error
    before = (rule.package / "fixtures/before.py").read_text(encoding="utf-8")
    after = (rule.package / "fixtures/after.py").read_text(encoding="utf-8")
    no_match = (rule.package / "fixtures/no_match.py").read_text(encoding="utf-8")
    findings = plugins["detector"].detect(before, "fixtures/before.py")
    if not findings:
        raise RegistryError(f"{rule.manifest['id']}: before fixture produced no findings")
    if plugins["detector"].detect(no_match, "fixtures/no_match.py"):
        raise RegistryError(f"{rule.manifest['id']}: no_match fixture produced findings")
    errors = plugins["validator"].validate_before(before, "fixtures/before.py", findings)
    if errors:
        raise RegistryError(f"{rule.manifest['id']}: before validation failed: {errors}")
    actual = plugins["codemod"].transform(before, "fixtures/before.py", findings)
    if actual != after:
        raise RegistryError(f"{rule.manifest['id']}: codemod output differs from after fixture")
    errors = plugins["validator"].validate_after(before, actual, "fixtures/before.py", findings)
    if errors:
        raise RegistryError(f"{rule.manifest['id']}: after validation failed: {errors}")
    if plugins["detector"].detect(actual, "fixtures/after.py"):
        raise RegistryError(f"{rule.manifest['id']}: codemod is not idempotent")


def canonical_registry_text(registry):
    return json.dumps(registry, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def validate_registry(rules_root, write=False):
    rules_root = Path(rules_root).resolve()
    packages = discover_rules(rules_root)
    for rule in packages:
        _validate_fixtures(rule)
    registry = build_registry(rules_root, packages)
    _validate(registry, rules_root / "schema" / "registry.schema.json", "registry")
    registry_path = rules_root / "registry.json"
    expected = canonical_registry_text(registry)
    if write:
        registry_path.write_text(expected, encoding="utf-8")
    elif not registry_path.is_file() or registry_path.read_text(encoding="utf-8") != expected:
        raise RegistryError("registry.json is missing or stale; run validate-registry --write after reviewing manifests")
    return registry, packages


def registry_sha256(rules_root):
    return _sha256(Path(rules_root) / "registry.json")
