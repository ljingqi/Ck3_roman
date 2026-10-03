# -*- coding: utf-8 -*-
"""Assert that a working-tree file differs from a git revision only in comments.

Docstrings are dropped from both ASTs before comparison, so a rewritten or
shortened docstring passes while any change to code, imports, decorators or
string literals fails.

    python tools/tests/verify_comments.py [--ref REV] FILE [FILE ...]
"""
import argparse
import ast
import difflib
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_DOC_OWNERS = (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


def _strip_docstrings(tree):
    for node in ast.walk(tree):
        if not isinstance(node, _DOC_OWNERS):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) \
                and isinstance(first.value.value, str):
            node.body = body[1:] or [ast.Pass()]
    return tree


def _dump(src):
    return ast.dump(_strip_docstrings(ast.parse(src)), indent=1).splitlines()


def _git_show(ref, rel):
    proc = subprocess.run(["git", "show", f"{ref}:{rel}"], cwd=ROOT,
                          capture_output=True)
    if proc.returncode:
        return None
    return proc.stdout.decode("utf-8")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="HEAD")
    ap.add_argument("files", nargs="+")
    args = ap.parse_args()
    bad = 0
    for rel in args.files:
        path = os.path.join(ROOT, rel)
        old = _git_show(args.ref, rel.replace("\\", "/"))
        if old is None:
            print(f"SKIP {rel}: not in {args.ref}")
            continue
        new = open(path, encoding="utf-8").read()
        a, b = _dump(old), _dump(new)
        if a == b:
            print(f"OK   {rel}: code identical to {args.ref} (comments/docstrings only)")
            continue
        bad += 1
        print(f"FAIL {rel}: code differs from {args.ref}")
        diff = list(difflib.unified_diff(a, b, lineterm="", n=2))
        for line in diff[:40]:
            print("    " + line)
    if bad:
        print(f"\n{bad} file(s) changed code — comments-only rule violated")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
