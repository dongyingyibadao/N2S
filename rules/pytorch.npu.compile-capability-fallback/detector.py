import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider


RULE_ID = "pytorch.npu.compile-capability-fallback"


def _config_name(test):
    if isinstance(test, cst.Attribute) and isinstance(test.value, cst.Name) and test.attr.value == "compile_model":
        return test.value.value
    return None


def _is_torch_compile(call):
    return (
        isinstance(call, cst.Call)
        and isinstance(call.func, cst.Attribute)
        and isinstance(call.func.value, cst.Name)
        and call.func.value.value == "torch"
        and call.func.attr.value == "compile"
    )


def _compile_call_count(node):
    class Visitor(cst.CSTVisitor):
        def __init__(self):
            self.count = 0

        def visit_Call(self, call):
            if _is_torch_compile(call):
                self.count += 1

    visitor = Visitor()
    node.visit(visitor)
    return visitor.count


class _Visitor(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, path):
        self.path = path
        self.parameters = []
        self.findings = []

    def visit_FunctionDef(self, node):
        self.parameters.append({parameter.name.value for parameter in node.params.params})

    def leave_FunctionDef(self, original_node):
        self.parameters.pop()

    def visit_If(self, node):
        config_name = _config_name(node.test)
        if (
            config_name
            and self.parameters
            and config_name in self.parameters[-1]
            and node.orelse is None
            and _compile_call_count(node.body) > 0
        ):
            position = self.get_metadata(PositionProvider, node)
            self.findings.append(
                {
                    "id": f"{RULE_ID}:{self.path}:{position.start.line}:compile-config-guard",
                    "line": position.start.line,
                    "column": position.start.column,
                    "message": "recognized config-controlled torch.compile block without NPU fallback",
                    "metadata": {"config_name": config_name, "compile_calls": _compile_call_count(node.body)},
                }
            )


def detect(source, path):
    try:
        module = cst.parse_module(source)
    except cst.ParserSyntaxError:
        return []
    visitor = _Visitor(path)
    MetadataWrapper(module).visit(visitor)
    return visitor.findings
