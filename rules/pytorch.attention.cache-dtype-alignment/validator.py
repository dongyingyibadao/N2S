import libcst as cst


def _count_prefix_casts(module):
    class Visitor(cst.CSTVisitor):
        def __init__(self):
            self.count = 0

        def visit_Assign(self, node):
            if len(node.targets) != 1 or not isinstance(node.targets[0].target, cst.Name) or node.targets[0].target.value != "prefix_embs":
                return
            value = node.value
            if not (isinstance(value, cst.Call) and isinstance(value.func, cst.Attribute) and isinstance(value.func.value, cst.Name)):
                return
            if value.func.value.value != "prefix_embs" or value.func.attr.value != "to":
                return
            if any(argument.keyword and argument.keyword.value == "dtype" and isinstance(argument.value, cst.Name) and argument.value.value == "prefix_dtype" for argument in value.args):
                self.count += 1

    visitor = Visitor()
    module.visit(visitor)
    return visitor.count


def validate_before(source, path, findings):
    try:
        cst.parse_module(source)
    except cst.ParserSyntaxError as error:
        return [f"source is not valid Python: {error}"]
    if not findings:
        return ["no detector findings supplied"]
    if any(not finding.get("metadata", {}).get("dtype_expression", "").endswith("q_proj.weight.dtype") for finding in findings):
        return ["detector did not provide an unambiguous q_proj weight dtype"]
    return []


def validate_after(before, after, path, findings):
    try:
        before_module = cst.parse_module(before)
        after_module = cst.parse_module(after)
    except cst.ParserSyntaxError as error:
        return [f"transformed source is not valid Python: {error}"]
    expected = len(findings)
    delta = _count_prefix_casts(after_module) - _count_prefix_casts(before_module)
    errors = []
    if delta != expected:
        errors.append(f"expected {expected} new prefix dtype casts, found {delta}")
    for finding in findings:
        expression = finding["metadata"]["dtype_expression"]
        if f"prefix_dtype = {expression}" not in after:
            errors.append(f"missing inferred projection dtype expression: {expression}")
    return errors
