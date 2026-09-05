import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider


WARNING = "torch.compile is disabled on Ascend NPU; using eager execution."


class _Transformer(cst.CSTTransformer):
    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, targets):
        self.targets = targets
        self.changed = 0

    def leave_If(self, original_node, updated_node):
        line = self.get_metadata(PositionProvider, original_node).start.line
        metadata = self.targets.get(line)
        if metadata is None:
            return updated_node
        config_name = metadata["config_name"]
        guarded_test = cst.parse_expression(
            f'{config_name}.compile_model and not str({config_name}.device).startswith("npu")'
        )
        fallback = cst.If(
            test=cst.parse_expression(f"{config_name}.compile_model"),
            body=cst.IndentedBlock(
                body=[cst.parse_statement(f'logging.warning("{WARNING}")\n')]
            ),
        )
        self.changed += 1
        return updated_node.with_changes(test=guarded_test, orelse=fallback)


def _has_logging_import(module):
    for statement in module.body:
        if not isinstance(statement, cst.SimpleStatementLine):
            continue
        for small in statement.body:
            if isinstance(small, cst.Import):
                if any(isinstance(alias.name, cst.Name) and alias.name.value == "logging" for alias in small.names):
                    return True
            if isinstance(small, cst.ImportFrom) and isinstance(small.module, cst.Name) and small.module.value == "logging":
                return True
    return False


def _insert_logging_import(module):
    body = list(module.body)
    index = 0
    if body and isinstance(body[0], cst.SimpleStatementLine) and body[0].body and isinstance(body[0].body[0], cst.Expr) and isinstance(body[0].body[0].value, cst.SimpleString):
        index = 1
    while index < len(body):
        statement = body[index]
        if not isinstance(statement, cst.SimpleStatementLine) or not statement.body:
            break
        first = statement.body[0]
        if not (isinstance(first, cst.ImportFrom) and isinstance(first.module, cst.Name) and first.module.value == "__future__"):
            break
        index += 1
    body.insert(index, cst.parse_statement("import logging\n"))
    return module.with_changes(body=body)


def transform(source, path, findings):
    module = cst.parse_module(source)
    targets = {finding["line"]: finding["metadata"] for finding in findings}
    transformer = _Transformer(targets)
    updated = MetadataWrapper(module).visit(transformer)
    if transformer.changed != len(findings):
        raise RuntimeError(f"expected {len(findings)} changes, made {transformer.changed}")
    if transformer.changed and not _has_logging_import(updated):
        updated = _insert_logging_import(updated)
    return updated.code
