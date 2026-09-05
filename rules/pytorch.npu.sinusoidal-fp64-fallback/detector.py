import ast

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider


RULE_ID = "pytorch.npu.sinusoidal-fp64-fallback"
LEROBOT_HELPER = "src/lerobot/utils/device_utils.py"
OPENPI_MODEL = "src/openpi/models_pytorch/pi0_pytorch.py"


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


def _is_float64_guard(node, device_name, dtype_name, device_value):
    if not (
        isinstance(node, cst.If)
        and isinstance(node.test, cst.BooleanOperation)
        and isinstance(node.test.operator, cst.And)
    ):
        return False
    device_ok = _comparison(
        node.test.left,
        device_name,
        cst.Equal,
        lambda value: _string_value(value) == device_value,
    )
    dtype_ok = _comparison(
        node.test.right,
        dtype_name,
        cst.Equal,
        lambda value: _attribute(value, "torch", "float64"),
    )
    return device_ok and dtype_ok and _returns_fp32(node)


def is_before_guard(node, device_name="device_type", dtype_name="target_dtype"):
    return _is_float64_guard(node, device_name, dtype_name, "mps")


def _is_applied_guard(node, device_name, dtype_name, strategy):
    if strategy == "insert-npu-guard":
        return _is_float64_guard(node, device_name, dtype_name, "npu")
    if not (
        isinstance(node, cst.If)
        and isinstance(node.test, cst.BooleanOperation)
        and isinstance(node.test.operator, cst.And)
    ):
        return False
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


def _has_sinusoidal_use(module):
    class Visitor(cst.CSTVisitor):
        def __init__(self):
            self.functions = []
            self.found = False

        def visit_FunctionDef(self, node):
            self.functions.append(node.name.value)

        def leave_FunctionDef(self, original_node):
            self.functions.pop()

        def visit_Call(self, node):
            if (
                not self.functions
                or "sinusoidal" not in self.functions[-1]
                or not isinstance(node.func, cst.Name)
                or node.func.value != "get_safe_dtype"
                or len(node.args) < 2
            ):
                return
            first, second = node.args[0].value, node.args[1].value
            if (
                _attribute(first, "torch", "float64")
                and isinstance(second, cst.Attribute)
                and isinstance(second.value, cst.Name)
                and second.attr.value == "type"
            ):
                self.found = True

    visitor = Visitor()
    module.visit(visitor)
    return visitor.found


def _parameters(function):
    return [parameter.name.value for parameter in function.params.params]


def _contains(function, predicate):
    class Visitor(cst.CSTVisitor):
        def __init__(self):
            self.found = False

        def on_visit(self, node):
            if predicate(node):
                self.found = True
            return not self.found

    visitor = Visitor()
    function.visit(visitor)
    return visitor.found


def _has_return_name(function, name):
    return _contains(
        function,
        lambda node: isinstance(node, cst.Return)
        and isinstance(node.value, cst.Name)
        and node.value.value == name,
    )


def _has_device_normalization(function):
    def predicate(node):
        if not isinstance(node, cst.Assign) or len(node.targets) != 1:
            return False
        target = node.targets[0].target
        return (
            isinstance(target, cst.Name)
            and target.value == "device"
            and isinstance(node.value, cst.Attribute)
            and isinstance(node.value.value, cst.Name)
            and node.value.value.value == "device"
            and node.value.attr.value == "type"
        )

    return _contains(function, predicate)


def _has_openpi_cpu_identity(function):
    def predicate(node):
        if not isinstance(node, cst.If):
            return False
        cpu_test = _comparison(
            node.test,
            "device_type",
            cst.Equal,
            lambda value: _string_value(value) == "cpu",
        )
        if not cpu_test:
            return False
        return _contains(
            node,
            lambda child: isinstance(child, cst.If)
            and _comparison(
                child.test,
                "target_dtype",
                cst.Equal,
                lambda value: _attribute(value, "torch", "float64"),
            )
            and any(
                isinstance(statement, cst.SimpleStatementLine)
                and any(
                    isinstance(small, cst.Return) and _attribute(small.value, "torch", "float64")
                    for small in statement.body
                )
                for statement in child.body.body
            ),
        )

    return _contains(function, predicate)


def _guards(function, device_name, dtype_name, strategy):
    matches = []

    class Visitor(cst.CSTVisitor):
        def visit_If(self, node):
            if (
                strategy == "extend-mps-guard"
                and is_before_guard(node, device_name, dtype_name)
            ) or (
                strategy == "insert-npu-guard"
                and _is_applied_guard(node, device_name, dtype_name, strategy)
            ):
                matches.append(node)

    function.visit(Visitor())
    return matches


class _Visitor(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, path, local_sinusoidal):
        self.path = path
        self.local_sinusoidal = local_sinusoidal
        self.findings = []

    def _add(self, node, adapter, strategy, device_name, dtype_name, message):
        position = self.get_metadata(PositionProvider, node)
        self.findings.append(
            {
                "id": f"{RULE_ID}:{self.path}:{position.start.line}:{adapter}",
                "line": position.start.line,
                "column": position.start.column,
                "message": message,
                "metadata": {
                    "adapter": adapter,
                    "strategy": strategy,
                    "device_name": device_name,
                    "dtype_name": dtype_name,
                },
            }
        )

    def visit_FunctionDef(self, node):
        if node.name.value != "get_safe_dtype":
            return True
        parameters = _parameters(node)
        if parameters == ["target_dtype", "device_type"] and self.local_sinusoidal:
            before = _guards(node, "device_type", "target_dtype", "extend-mps-guard")
            for guard in before:
                self._add(
                    guard,
                    "local-sinusoidal-mps-guard",
                    "extend-mps-guard",
                    "device_type",
                    "target_dtype",
                    "recognized local sinusoidal MPS-only float64 fallback",
                )
            if (
                not before
                and self.path.endswith(OPENPI_MODEL)
                and _has_return_name(node, "target_dtype")
                and _has_openpi_cpu_identity(node)
                and not _guards(node, "device_type", "target_dtype", "insert-npu-guard")
            ):
                self._add(
                    node,
                    "openpi-local-safe-dtype",
                    "insert-npu-guard",
                    "device_type",
                    "target_dtype",
                    "recognized OpenPI-local sinusoidal safe-dtype helper without an NPU float64 fallback",
                )
        elif (
            parameters == ["dtype", "device"]
            and self.path.endswith(LEROBOT_HELPER)
            and _has_device_normalization(node)
            and _has_return_name(node, "dtype")
        ):
            for guard in _guards(node, "device", "dtype", "extend-mps-guard"):
                self._add(
                    guard,
                    "lerobot-shared-safe-dtype",
                    "extend-mps-guard",
                    "device",
                    "dtype",
                    "recognized LeRobot shared MPS-only float64 fallback used by VLA sinusoidal helpers",
                )
        return False


def detect(source, path):
    try:
        module = cst.parse_module(source)
    except cst.ParserSyntaxError:
        return []
    visitor = _Visitor(path, _has_sinusoidal_use(module))
    MetadataWrapper(module).visit(visitor)
    return visitor.findings
