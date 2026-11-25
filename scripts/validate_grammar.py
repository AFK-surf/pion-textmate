#!/usr/bin/env python3
"""Validate syntaxes/pion.tmLanguage.json (and optionally cross-check against AFK-surf/pion)."""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys


ROOT = pathlib.Path(__file__).resolve().parent.parent
GRAMMAR_PATH = ROOT / "syntaxes" / "pion.tmLanguage.json"


def walk_rules(obj, repo_keys: set[str], regexes: list[tuple[str, str]], errors: list[str], path: str = "$") -> None:
    if isinstance(obj, dict):
        inc = obj.get("include")
        if isinstance(inc, str) and inc.startswith("#"):
            target = inc[1:]
            if target not in repo_keys:
                errors.append(f"{path}: unresolved repository include #{target}")
        for field in ("match", "begin", "end", "while"):
            val = obj.get(field)
            if isinstance(val, str):
                regexes.append((f"{path}.{field}", val))
        for k, v in obj.items():
            walk_rules(v, repo_keys, regexes, errors, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            walk_rules(item, repo_keys, regexes, errors, f"{path}[{i}]")


def extract_lexer_keywords(lexer_src: str) -> set[str]:
    m = re.search(r"fn keyword_or_ident\b.*?^}", lexer_src, flags=re.M | re.S)
    if not m:
        raise RuntimeError("Could not locate keyword_or_ident in lexer.pion")
    return set(re.findall(r'word == "([a-z_]+)"', m.group(0)))


def extract_compiler_builtin_types(types_src: str) -> set[str]:
    m = re.search(
        r"TyName\(name, args, sp\) => \{.*?(?=let via_alias = tc_is_imported_pkg_alias)",
        types_src,
        flags=re.S,
    )
    if not m:
        raise RuntimeError("Could not locate TyName builtin type table in types.pion")
    return set(re.findall(r'name == "([A-Z][A-Za-z0-9_]*)"', m.group(0)))


def extract_grammar_word_list(rule_match: str) -> set[str]:
    m = re.fullmatch(r"\\b\(([A-Za-z0-9_|]+)\)\\b", rule_match)
    if not m:
        raise RuntimeError(f"Unexpected word-list regex format: {rule_match!r}")
    return set(m.group(1).split("|"))


def run_regression_checks(repo: dict, errors: list[str]) -> int:
    checked = 0

    # 1. JSX open tag end regex must NOT match the '>' of '=>' (prop=>{ expr })
    jsx_open = [r for r in repo["jsx"]["patterns"] if r.get("name") == "meta.tag.jsx.open.pion"][0]
    jsx_end = re.compile(jsx_open["end"])
    sample_jsx = "<ui::Card on_press=>{ on_click() } active>"
    m_end = jsx_end.search(sample_jsx)
    if not m_end or m_end.start() != len(sample_jsx) - 1:
        errors.append(
            f"JSX open tag end regex matched prematurely on {sample_jsx!r}: "
            f"{m_end.span() if m_end else None}"
        )
    jsx_inner_matches = [r.get("match") for r in jsx_open.get("patterns", []) if "match" in r]
    if "=>" not in jsx_inner_matches or jsx_inner_matches.index("=>") > jsx_inner_matches.index("="):
        errors.append("JSX open tag inner patterns must match '=>' before '='")
    checked += 1

    # 2. Contextual 'test' keyword matches 'test "name" {' but not identifier usage 'let test = 1'
    test_rules = [r for r in repo["keywords"]["patterns"] if r.get("name") == "keyword.other.test.pion"]
    if not test_rules:
        errors.append("Missing keyword.other.test.pion rule")
    else:
        tp = re.compile(test_rules[0]["match"])
        if not tp.search('test "shape area" {'):
            errors.append('keyword.other.test.pion failed to match `test "shape area" {`')
        if tp.search("let test = 1"):
            errors.append("keyword.other.test.pion falsely matched `let test = 1`")
    checked += 1

    # 3. Labeled parameter rule must match `opt? : Int` / `label~ : String` but NOT `f(x?)`
    param_rules = [
        r for r in repo["namespaces-and-calls"]["patterns"]
        if r.get("captures", {}).get("1", {}).get("name") == "variable.parameter.labeled.pion"
    ]
    if not param_rules:
        errors.append("Missing variable.parameter.labeled.pion rule")
    else:
        pp = re.compile(param_rules[0]["match"])
        if not pp.search('fn f(opt? : Int, label~ : String = "")'):
            errors.append("Labeled parameter rule failed to match parameter declarations")
        if pp.search("f(x?)") or pp.search("g(x?, y)"):
            errors.append("Labeled parameter rule falsely matched error-propagation `x?` in call")
    checked += 1

    # 4. SCREAMING_SNAKE_CASE constants matched as constant.other.pion; single-letter generics untouched
    const_rules = [r for r in repo["constants"]["patterns"] if r.get("name") == "constant.other.pion"]
    if not const_rules:
        errors.append("Missing constant.other.pion rule")
    else:
        cp = re.compile(const_rules[0]["match"])
        if not cp.search("MAX_SIZE"):
            errors.append("constant.other.pion failed to match MAX_SIZE")
        if cp.search("Array") or cp.search("T") or cp.search("IO"):
            errors.append("constant.other.pion over-matched type/generic name")
    checked += 1

    # 5. Unterminated string / char end regex stops at end-of-line
    if not re.compile(repo["strings"]["end"]).search("unterminated"):
        errors.append("strings.end must terminate at EOL for unterminated strings")
    for cr in repo["chars-and-bytes"]["patterns"]:
        if not re.compile(cr["end"]).search("unterminated"):
            errors.append(f"{cr.get('name')}.end must terminate at EOL")
    checked += 1

    # 6. Raw string rule must not duplicate string.unquoted.raw.pion on outer rule + capture 2
    if "name" in repo["raw-string"]:
        errors.append("raw-string rule duplicates scope on outer rule and capture 2")
    checked += 1

    return checked


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pion-repo", type=pathlib.Path, default=None, help="Optional AFK-surf/pion checkout for two-way parity")
    args = ap.parse_args()

    grammar = json.loads(GRAMMAR_PATH.read_text(encoding="utf-8"))
    errors: list[str] = []

    if grammar.get("scopeName") != "source.pion":
        errors.append(f"Expected scopeName 'source.pion', got {grammar.get('scopeName')!r}")
    if "pion" not in (grammar.get("fileTypes") or []):
        errors.append("fileTypes must include 'pion'")

    repo = grammar.get("repository") or {}
    repo_keys = set(repo.keys())
    regexes: list[tuple[str, str]] = []
    walk_rules(grammar, repo_keys, regexes, errors)

    for loc, pattern in regexes:
        try:
            re.compile(pattern)
        except re.error as exc:
            errors.append(f"{loc}: invalid regex {pattern!r}: {exc}")

    parity_msg = ""
    if args.pion_repo is not None:
        lexer_path = args.pion_repo / "compiler" / "src" / "core" / "lexer.pion"
        types_path = args.pion_repo / "compiler" / "src" / "core" / "types.pion"

        lexer_kws = extract_lexer_keywords(lexer_path.read_text(encoding="utf-8"))
        grammar_kws: set[str] = set()
        for section in ("keywords", "constants"):
            for rule in repo.get(section, {}).get("patterns", []):
                match = rule.get("match", "")
                if re.fullmatch(r"\\b\([a-z_|]+\)\\b", match):
                    grammar_kws |= extract_grammar_word_list(match)
        missing_kws = sorted(lexer_kws - grammar_kws)
        extra_kws = sorted((grammar_kws - lexer_kws) - {"self"})
        if missing_kws:
            errors.append(f"Keywords in lexer.pion missing from grammar: {missing_kws}")
        if extra_kws:
            errors.append(f"Non-existent keywords in grammar not in lexer.pion: {extra_kws}")

        compiler_types = extract_compiler_builtin_types(types_path.read_text(encoding="utf-8"))
        grammar_types: set[str] = set()
        for rule in repo.get("types", {}).get("patterns", []):
            if rule.get("name") in ("support.type.primitive.pion", "support.type.builtin.pion"):
                grammar_types |= extract_grammar_word_list(rule["match"])
        missing_types = sorted(compiler_types - grammar_types)
        extra_types = sorted(grammar_types - compiler_types)
        if missing_types:
            errors.append(f"Built-in types in types.pion missing from grammar: {missing_types}")
        if extra_types:
            errors.append(f"Non-existent built-in types in grammar not in types.pion: {extra_types}")
        parity_msg = f", {len(lexer_kws)} lexer keywords + {len(compiler_types)} builtin types exact match"

    regressions = run_regression_checks(repo, errors)

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(
        f"OK: {GRAMMAR_PATH.relative_to(ROOT)} validated "
        f"({len(repo_keys)} repo rules, {len(regexes)} regexes{parity_msg}, "
        f"{regressions} regression checks passed)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
