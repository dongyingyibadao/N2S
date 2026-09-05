import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider


class _Transformer(cst.CSTTransformer):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, targets):
        self.targets = targets
        self.changed = 0

    def leave_SimpleStatementLine(self, original_node, updated_node):
        line = self.get_metadata(PositionProvider, original_node).start.line
        metadata = self.targets.get(line)
        if metadata is None:
            return updated_node
        expression = metadata["dtype_expression"]
        self.changed += 1
        return cst.FlattenSentinel(
            [
                updated_node,
                cst.parse_statement(f"prefix_dtype = {expression}\n"),
                cst.parse_statement("prefix_embs = prefix_embs.to(dtype=prefix_dtype)\n"),
            ]
        )


def transform(source, path, findings):
    module = cst.parse_module(source)
    targets = {finding["line"]: finding["metadata"] for finding in findings}
    transformer = _Transformer(targets)
    updated = MetadataWrapper(module).visit(transformer)
    if transformer.changed != len(findings):
        raise RuntimeError(f"expected {len(findings)} changes, made {transformer.changed}")
    return updated.code
