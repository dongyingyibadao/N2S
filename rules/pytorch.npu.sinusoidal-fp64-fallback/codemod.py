import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider


class _Transformer(cst.CSTTransformer):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, targets):
        self.targets = targets
        self.changed = 0

    def leave_If(self, original_node, updated_node):
        line = self.get_metadata(PositionProvider, original_node).start.line
        metadata = self.targets.get(line)
        if metadata is None or metadata["strategy"] != "extend-mps-guard":
            return updated_node
        replacement = cst.Comparison(
            left=cst.Name(metadata["device_name"]),
            comparisons=[
                cst.ComparisonTarget(
                    operator=cst.In(),
                    comparator=cst.Set(
                        elements=[cst.Element(cst.SimpleString('"mps"')), cst.Element(cst.SimpleString('"npu"'))]
                    ),
                )
            ],
        )
        self.changed += 1
        return updated_node.with_changes(test=updated_node.test.with_changes(left=replacement))

    def leave_FunctionDef(self, original_node, updated_node):
        line = self.get_metadata(PositionProvider, original_node).start.line
        metadata = self.targets.get(line)
        if metadata is None or metadata["strategy"] != "insert-npu-guard":
            return updated_node
        if not isinstance(updated_node.body, cst.IndentedBlock):
            return updated_node
        guard = cst.parse_statement(
            f'if {metadata["device_name"]} == "npu" and '
            f'{metadata["dtype_name"]} == torch.float64:\n'
            "    return torch.float32\n"
        )
        body = list(updated_node.body.body)
        index = 0
        if (
            body
            and isinstance(body[0], cst.SimpleStatementLine)
            and body[0].body
            and isinstance(body[0].body[0], cst.Expr)
            and isinstance(body[0].body[0].value, (cst.SimpleString, cst.ConcatenatedString))
        ):
            index = 1
        body.insert(index, guard)
        self.changed += 1
        return updated_node.with_changes(body=updated_node.body.with_changes(body=body))


def transform(source, path, findings):
    module = cst.parse_module(source)
    targets = {finding["line"]: finding["metadata"] for finding in findings}
    if len(targets) != len(findings):
        raise RuntimeError("multiple findings target the same source line")
    transformer = _Transformer(targets)
    updated = MetadataWrapper(module).visit(transformer)
    if transformer.changed != len(findings):
        raise RuntimeError(f"expected {len(findings)} changes, made {transformer.changed}")
    return updated.code
