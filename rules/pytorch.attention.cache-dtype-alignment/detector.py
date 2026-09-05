import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider


RULE_ID = "pytorch.attention.cache-dtype-alignment"


def _is_q_proj_dtype(node):
    return (
        isinstance(node, cst.Attribute)
        and node.attr.value == "dtype"
        and isinstance(node.value, cst.Attribute)
        and node.value.attr.value == "weight"
        and isinstance(node.value.value, cst.Attribute)
        and node.value.value.attr.value == "q_proj"
    )


def _dtype_expressions(module):
    class Visitor(cst.CSTVisitor):
        def __init__(self):
            self.nodes = []

        def visit_Attribute(self, node):
            if _is_q_proj_dtype(node):
                self.nodes.append(node)

    visitor = Visitor()
    module.visit(visitor)
    return sorted({module.code_for_node(node) for node in visitor.nodes})


def _is_prefix_assignment(node):
    if not isinstance(node, cst.Assign) or len(node.targets) != 1 or not isinstance(node.targets[0].target, cst.Tuple):
        return False
    elements = node.targets[0].target.elements
    first = elements[0].value if elements and isinstance(elements[0], cst.Element) else None
    return (
        isinstance(first, cst.Name)
        and first.value == "prefix_embs"
        and isinstance(node.value, cst.Call)
        and isinstance(node.value.func, cst.Attribute)
        and node.value.func.attr.value == "embed_prefix"
    )


def _function_cache_use(function):
    class Visitor(cst.CSTVisitor):
        def __init__(self):
            self.found = False

        def visit_Arg(self, node):
            if node.keyword and node.keyword.value == "inputs_embeds" and isinstance(node.value, cst.List):
                values = [element.value for element in node.value.elements if isinstance(element, cst.Element)]
                if values and isinstance(values[0], cst.Name) and values[0].value == "prefix_embs":
                    self.found = True

    visitor = Visitor()
    function.visit(visitor)
    return visitor.found


def _function_has_prefix_cast(function):
    class Visitor(cst.CSTVisitor):
        def __init__(self):
            self.found = False

        def visit_Assign(self, node):
            if len(node.targets) != 1 or not isinstance(node.targets[0].target, cst.Name) or node.targets[0].target.value != "prefix_embs":
                return
            value = node.value
            if isinstance(value, cst.Call) and isinstance(value.func, cst.Attribute) and isinstance(value.func.value, cst.Name) and value.func.value.value == "prefix_embs" and value.func.attr.value == "to":
                self.found = True

    visitor = Visitor()
    function.visit(visitor)
    return visitor.found


class _Visitor(cst.CSTVisitor):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, path, dtype_expression):
        self.path = path
        self.dtype_expression = dtype_expression
        self.functions = []
        self.findings = []

    def visit_FunctionDef(self, node):
        self.functions.append((_function_cache_use(node), _function_has_prefix_cast(node)))

    def leave_FunctionDef(self, original_node):
        self.functions.pop()

    def visit_Assign(self, node):
        if self.functions and self.functions[-1] == (True, False) and _is_prefix_assignment(node):
            position = self.get_metadata(PositionProvider, node)
            self.findings.append(
                {
                    "id": f"{RULE_ID}:{self.path}:{position.start.line}:prefix-cache-boundary",
                    "line": position.start.line,
                    "column": position.start.column,
                    "message": "recognized unaligned prefix embedding before cached attention",
                    "metadata": {"dtype_expression": self.dtype_expression, "tensor": "prefix_embs"},
                }
            )


def detect(source, path):
    try:
        module = cst.parse_module(source)
    except cst.ParserSyntaxError:
        return []
    expressions = _dtype_expressions(module)
    if len(expressions) != 1:
        return []
    visitor = _Visitor(path, expressions[0])
    MetadataWrapper(module).visit(visitor)
    return visitor.findings
