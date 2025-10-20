"""Used to generate the sed script from PySide6 type stubs.

$ python -m venv .venv
$ .venv/bin/pip install astroid
$ .venv/bin/python process_enums.py --binding PySide2,PySide6 PySide6-stubs/ 1> pyside6.sed 2> conflicts.md
"""
import argparse
import collections
from collections.abc import Callable, Iterable
import os.path
import pathlib
import re
import sys

import astroid
from astroid.builder import AstroidBuilder
from astroid.manager import AstroidManager


def resolve_import_alias(
    name: str, import_names: Iterable[tuple[str, str | None]]
) -> str:
    """Resolve a name from an aliased import to its original name.

    Args:
        name: The potentially aliased name to resolve.
        import_names: The pairs of original names and aliases from the import.

    Returns:
        The original name.
    """
    resolved_name = name

    for import_name, imported_as in import_names:
        if import_name == name:
            break
        if imported_as == name:
            resolved_name = import_name
            break

    return resolved_name


def get_full_import_name(import_from: astroid.nodes.ImportFrom, name: str) -> str:
    """Get the full path of a name from a ``from x import y`` statement.

    Args:
        import_from: The astroid node to resolve the name of.
        name: The short name or alias of what was imported.
            This is ``y`` in ``from x import y``
            and ``z`` in ``from x import y as z``.

    Returns:
        str: The full import path of the name.
    """
    partial_basename = resolve_import_alias(name, import_from.names)

    module_name = import_from.modname
    if import_from.level:
        module = import_from.root()
        assert isinstance(module, astroid.nodes.Module)
        module_name = module.relative_to_absolute_name(
            import_from.modname, level=import_from.level
        )

    return f"{module_name}.{partial_basename}"


def resolve_qualname(node: astroid.nodes.NodeNG, basename: str) -> str:
    """Resolve where a node is defined to get its fully qualified name.

    Args:
        node: The node representing the base name.
        basename: The partial base name to resolve.

    Returns:
        The fully resolved base name.
    """
    full_basename = basename

    top_level_name = re.sub(r"\(.*\)", "", basename).split(".", 1)[0]
    if isinstance(node, astroid.nodes.LocalsDictNodeNG):
        lookup_node = node
    else:
        lookup_node = node.scope()

    assigns = lookup_node.lookup(top_level_name)[1]

    for assignment in assigns:
        if isinstance(assignment, astroid.nodes.ImportFrom):
            import_name = get_full_import_name(assignment, top_level_name)
            full_basename = basename.replace(top_level_name, import_name, 1)
            break
        if isinstance(assignment, astroid.nodes.Import):
            import_name = resolve_import_alias(top_level_name, assignment.names)
            full_basename = basename.replace(top_level_name, import_name, 1)
            break
        if isinstance(assignment, astroid.nodes.ClassDef):
            full_basename = assignment.qname()
            break
        if isinstance(assignment, astroid.nodes.AssignName):
            full_basename = f"{assignment.scope().qname()}.{assignment.name}"

    if isinstance(node, astroid.nodes.Call):
        full_basename = re.sub(r"\(.*\)", "()", full_basename)

    if full_basename.startswith("builtins."):
        return full_basename[len("builtins.") :]

    if full_basename.startswith("__builtin__."):
        return full_basename[len("__builtin__.") :]

    return full_basename


def get_full_basenames(node: astroid.nodes.ClassDef) -> Iterable[str]:
    """Resolve the partial names of a class' bases to fully qualified names.

    Args:
        node: The class definition node to resolve the bases of.

    Returns:
        The fully qualified names.
    """
    for base in node.bases:
        yield _resolve_annotation(base)


def _resolve_annotation(annotation: astroid.nodes.NodeNG) -> str:
    resolved: str

    if isinstance(annotation, astroid.nodes.Const):
        resolved = resolve_qualname(annotation, str(annotation.value))
    elif isinstance(annotation, astroid.nodes.Name):
        resolved = resolve_qualname(annotation, annotation.name)
    elif isinstance(annotation, astroid.nodes.Attribute):
        resolved = resolve_qualname(annotation, annotation.as_string())
    elif isinstance(annotation, astroid.nodes.Subscript):
        value = _resolve_annotation(annotation.value)
        slice_node = annotation.slice
        # astroid.Index was removed in astroid v3
        if hasattr(astroid.nodes, "Index") and isinstance(
            slice_node, astroid.nodes.Index
        ):
            slice_node = slice_node.value
        if value == "Literal":
            if isinstance(slice_node, astroid.nodes.Tuple):
                elts = slice_node.elts
            else:
                elts = [slice_node]
            slice_ = ", ".join(
                (
                    elt.as_string()
                    if isinstance(elt, astroid.nodes.Const)
                    else _resolve_annotation(elt)
                )
                for elt in elts
            )
        elif isinstance(slice_node, astroid.nodes.Tuple):
            slice_ = ", ".join(_resolve_annotation(elt) for elt in slice_node.elts)
        else:
            slice_ = _resolve_annotation(slice_node)
        resolved = f"{value}[{slice_}]"
    elif isinstance(annotation, astroid.nodes.Tuple):
        resolved = (
            "(" + ", ".join(_resolve_annotation(elt) for elt in annotation.elts) + ")"
        )
    elif isinstance(annotation, astroid.nodes.List):
        resolved = (
            "[" + ", ".join(_resolve_annotation(elt) for elt in annotation.elts) + "]"
        )
    elif isinstance(annotation, astroid.nodes.BinOp) and annotation.op == "|":
        left = _resolve_annotation(annotation.left)
        right = _resolve_annotation(annotation.right)
        resolved = f"{left} | {right}"
    else:
        resolved = annotation.as_string()

    if resolved.startswith("typing."):
        return resolved[len("typing.") :]

    # Sphinx is capable of linking anything in the same module
    # without needing a fully qualified path.
    module_prefix = annotation.root().name + "."
    if resolved.startswith(module_prefix):
        return resolved[len(module_prefix) :]

    return resolved


def get_assign_target_name(
    node: astroid.nodes.Assign | astroid.nodes.AnnAssign,
) -> str | None:
    """Get the name of the assignment of the given node.

    Assignments to multiple names are ignored.

    Args:
        node: The node to get the assignment value from.

    Returns:
        The name that is assigned to.
    """
    target = _get_assign_target_node(node)

    if isinstance(target, astroid.nodes.AssignName):
        return target.name

    if isinstance(target, astroid.nodes.AssignAttr):
        return target.attrname

    return None


def _get_assign_target_node(
    node: astroid.nodes.Assign | astroid.nodes.AnnAssign,
) -> astroid.nodes.NodeNG | None:
    """Get the target of the given assignment node.

    Assignments to multiple names are ignored.

    Args:
        node: The node to get the assignment value from.

    Returns:
        The node representing the name that is assigned to.
    """
    try:
        targets = node.targets
    except AttributeError:
        targets = [node.target]

    if len(targets) == 1:
        target = targets[0]
        if isinstance(target, (astroid.nodes.AssignName, astroid.nodes.AssignAttr)):
            return target

    return None


class Parser:
    def __init__(self) -> None:
        self._qual_name_stack: list[str] = []

    def _get_qual_name(self, name: str) -> str:
        return ".".join(self._qual_name_stack + [name])

    def _parse_file(self, file_path: str, condition: Callable[[str], bool]) -> list[tuple[str, str]]:
        directory, filename = os.path.split(file_path)
        module_parts: collections.deque[str] = collections.deque()
        if filename != "__init__.py" and filename != "__init__.pyi":
            module_part = os.path.splitext(filename)[0]
            module_parts = collections.deque([module_part])

        while directory and condition(directory):
            directory, module_part = os.path.split(directory)
            if module_part:
                module_parts.appendleft(module_part)

        module_name = ".".join(module_parts)
        node = AstroidBuilder(AstroidManager()).file_build(file_path, module_name)
        return self.parse(node)

    def parse_file(self, file_path: str) -> list[tuple[str, str]]:
        return self._parse_file(
            file_path,
            lambda directory: (
                os.path.isfile(os.path.join(directory, "__init__.py"))
                or os.path.isfile(os.path.join(directory, "__init__.pyi"))
            ),
        )

    def parse(self, node: astroid.nodes.NodeNG) -> list[tuple[str, str]]:
        results = []

        node_type = node.__class__.__name__.lower()
        parse_func = getattr(self, "parse_" + node_type, None)
        if parse_func:
            results = parse_func(node)
        else:
            for child in node.get_children():
                results.extend(self.parse(child))

        return results

    def parse_classdef(self, node: astroid.nodes.ClassDef) -> list[tuple[str, str]]:
        results: list[tuple[str, str]] = []

        self._qual_name_stack.append(node.name)

        bases = get_full_basenames(node)
        if any(base.split(".", 1)[0] == "enum" for base in bases):
            for child in node.body:
                if isinstance(child, astroid.nodes.AnnAssign):
                    results.extend(self._parse_enum_member(child))
        else:
            for child in node.body:
                if isinstance(child, astroid.nodes.ClassDef):
                    results.extend(self.parse_classdef(child))

        self._qual_name_stack.pop()

        return results

    def _parse_enum_member(self, node: astroid.nodes.AnnAssign) -> list[tuple[str, str]]:
        # Don't parse module level assignments to class attributes
        if isinstance(node.target, astroid.nodes.AssignAttr):
            return []

        target = get_assign_target_name(node)
        if not target:
            return []

        qual_name = self._get_qual_name(target)
        return [(target, qual_name)]


    def parse_module(self, node: astroid.nodes.Module) -> list[tuple[str, str]]:
        results: list[tuple[str, str]] = []

        name = node.name.split(".")[-1]
        self._qual_name_stack = [name]

        for child in node.get_children():
            if isinstance(child, astroid.nodes.ClassDef):
                results.extend(self.parse_classdef(child))

        return results


_PREFFERED_QT_MODULES = ("QtCore", "QtGui", "QtWidgets")
def _sort_key(member_qual_name: tuple[str, str]) -> tuple[int, str, bool, str]:
    member, qual_name = member_qual_name
    return (
        # Sort into reverse length order so that the name of a short member
        # will never be substituted before a longer member that starts with the name of the shorter member.
        # Eg. "Read" will not be subsituted before "ReadWrite".
        -len(member),
        # Group members with the same name together.
        member,
        # Prefer a subsitution to the more common Qt submodules.
        qual_name.split(".", 1)[0] in _PREFFERED_QT_MODULES,
        # Finally, sort by the Qt submodule to give a more stable storting.
        qual_name,
    )


def _to_sed_script(substitutions: Iterable[tuple[str, str]]) -> list[str]:
    result: list[str] = []

    member_qual_names: collections.defaultdict[str, list[str]] = collections.defaultdict(list)
    for member, qual_name in sorted(substitutions, key=_sort_key):
        member_qual_names[member].append(qual_name)

        # Do the straight substitution for any variable
        result.append(f"s/([^a-zA-Z0-9_.]|^)[a-zA-PR-Z0-9_.]([a-su-z0-9_.][a-zA-Z0-9_.]*)?\\.{member}([^a-zA-Z0-9_.]|$)/\\1{qual_name}\\3/g")

        # Substitute direct accesses to the old location
        # For example, QtWidgets.QAbstractItemView.MultiSelection becomes
        # QtWidgets.QAbstractItemView.SelectionMode.MultiSelection.
        qual_parts = qual_name.split(".")
        old = f"{'.'.join(qual_parts[:-2])}.{qual_parts[-1]}"
        result.append(f"s/([^a-zA-Z0-9_.]|^)[a-zA-Z0-9_.]+\\.{old}([^a-zA-Z0-9_.]|$)/\\1{qual_name}\\2/g")

    for member, qual_names in member_qual_names.items():
        if len(qual_names) > 1:
            print(f"* Will substitute `{member}` to `{qual_names[-1]}`, but could be any of `{'`, `'.join(qual_names)}`", file=sys.stderr)

    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "-b", "--binding",
        action="append",
        help="Also substitute a Qt binding import. For example, '-b PySide2,PySide6' would substitute 'PySide2' for 'PySide6'",
    )

    parser.add_argument(
        "file_or_directory",
        nargs="+",
        help="The files or directories of stub files to find PySide type stubs in."
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    argparser = _build_parser()
    args = argparser.parse_args(argv)

    parser = Parser()
    substitutions: list[tuple[str, str]] = [
        # https://doc.qt.io/qtforpython-6/faq/porting_from2.html#class-function-deprecations
        ("MidButton", "QtCore.Qt.MouseButton.MiddleButton"),
    ]
    for file_or_directory in args.file_or_directory:
        if pathlib.Path(file_or_directory).is_file():
            substitutions.extend(parser.parse_file(file_or_directory))
        else:
            for dirpath, _, filenames in pathlib.Path(file_or_directory).walk():
                for filename in filenames:
                    if filename.endswith(".pyi"):
                        substitutions.extend(
                            parser.parse_file(str(dirpath / filename))
                        )

    sed_script = _to_sed_script(substitutions)
    for binding in args.binding:
        old, new = binding.split(",")
        print(f"s/import {old}/import {new}/"),
        print(f"s/from {old} import/from {new} import/"),
    for line in sed_script:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
