import ast
from collections import Counter

import libcst as cst


STRATEGIES = {"extend-mps-guard", "insert-npu-guard"}


def _attribute(node, owner, name):
    return (
        isinstance(node, cst.Attribute)
        and isinstance(node.value, cst.Name)
        and node.value.value == owner
        and node.attr.value == name
    )


def _string_value(node):
    if not isinstance(node, cst.SimpleString):
        return None
    try:
        value = ast.literal_eval(node.value)
    except (SyntaxError, ValueError):
        return None
    return value if isinstance(value, str) else None


def _comparison(node, name, operator, comparator):
    return (
        isinstance(node, cst.Comparison)
        and len(node.comparisons) == 1
        and isinstance(node.left, cst.Name)
        and node.left.value == name
        and isinstance(node.comparisons[0].operator, operator)
        and comparator(node.comparisons[0].comparator)
    )


def _returns_fp32(node):
    return any(
        isinstance(statement, cst.SimpleStatementLine)
        and any(isinstance(small, cst.Return) and _attribute(small.value, "torch", "float32") for small in statement.body)
        for statement in node.body.body
    )


def _is_applied_guard(node, key):
    strategy, device_name, dtype_name = key
    if not (
        isinstance(node, cst.If)
        and isinstance(node.test, cst.BooleanOperation)
        and isinstance(node.test.operator, cst.And)
    ):
        return False
    if strategy == "insert-npu-guard":
        device_ok = _comparison(
            node.test.left,
            device_name,
            cst.Equal,
            lambda value: _string_value(value) == "npu",
        )
    else:
        device_ok = _comparison(
            node.test.left,
            device_name,
            cst.In,
            lambda value: isinstance(value, cst.Set)
            and {
                _string_value(element.value)
                for element in value.elements
                if isinstance(element, cst.Element)
            }
            == {"mps", "npu"},
        )
    dtype_ok = _comparison(
        node.test.right,
        dtype_name,
        cst.Equal,
        lambda value: _attribute(value, "torch", "float64"),
    )
    return device_ok and dtype_ok and _returns_fp32(node)


def _count_applied(module, key):
    class Visitor(cst.CSTVisitor):
        def __init__(self):
            self.count = 0

        def visit_If(self, node):
            if _is_applied_guard(node, key):
                self.count += 1

    visitor = Visitor()
    module.visit(visitor)
    return visitor.count


def _finding_key(finding):
    metadata = finding.get("metadata", {})
    return metadata.get("strategy"), metadata.get("device_name"), metadata.get("dtype_name")


def validate_before(source, path, findings):
    try:
        cst.parse_module(source)
    except cst.ParserSyntaxError as error:
        return [f"source is not valid Python: {error}"]
    if not findings:
        return ["no detector findings supplied"]
    errors = []
    for finding in findings:
        strategy, device_name, dtype_name = _finding_key(finding)
        if strategy not in STRATEGIES:
            errors.append(f"unknown adapter strategy: {strategy}")
        if not device_name or not dtype_name:
            errors.append("detector did not provide device and dtype variable names")
    return errors


def validate_after(before, after, path, findings):
    try:
        before_module = cst.parse_module(before)
        after_module = cst.parse_module(after)
    except cst.ParserSyntaxError as error:
        return [f"transformed source is not valid Python: {error}"]
    errors = []
    expected = Counter(_finding_key(finding) for finding in findings)
    for key, count in expected.items():
        delta = _count_applied(after_module, key) - _count_applied(before_module, key)
        if delta != count:
            errors.append(f"expected {count} new applied guards for {key}, found {delta}")
    return errors
