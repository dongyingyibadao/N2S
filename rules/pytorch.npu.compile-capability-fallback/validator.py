import libcst as cst


def _is_torch_compile(node):
    return (
        isinstance(node, cst.Call)
        and isinstance(node.func, cst.Attribute)
        and isinstance(node.func.value, cst.Name)
        and node.func.value.value == "torch"
        and node.func.attr.value == "compile"
    )


def _counts(module):
    class Visitor(cst.CSTVisitor):
        def __init__(self):
            self.compile_calls = 0
            self.guards = 0
            self.warnings = 0

        def visit_Call(self, node):
            if _is_torch_compile(node):
                self.compile_calls += 1
            if isinstance(node.func, cst.Attribute) and isinstance(node.func.value, cst.Name) and node.func.value.value == "logging" and node.func.attr.value == "warning":
                self.warnings += 1

        def visit_If(self, node):
            code = cst.Module([]).code_for_node(node.test)
            if ".compile_model and not str(" in code and '.device).startswith("npu")' in code:
                self.guards += 1

    visitor = Visitor()
    module.visit(visitor)
    return visitor.compile_calls, visitor.guards, visitor.warnings


def validate_before(source, path, findings):
    try:
        cst.parse_module(source)
    except cst.ParserSyntaxError as error:
        return [f"source is not valid Python: {error}"]
    return [] if findings else ["no detector findings supplied"]


def validate_after(before, after, path, findings):
    try:
        before_counts = _counts(cst.parse_module(before))
        after_counts = _counts(cst.parse_module(after))
    except cst.ParserSyntaxError as error:
        return [f"transformed source is not valid Python: {error}"]
    errors = []
    expected = len(findings)
    if after_counts[0] != before_counts[0]:
        errors.append("torch.compile call count changed")
    if after_counts[1] - before_counts[1] != expected:
        errors.append(f"expected {expected} new NPU guards")
    if after_counts[2] - before_counts[2] != expected:
        errors.append(f"expected {expected} new fallback warnings")
    return errors
