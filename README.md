# pion-textmate

TextMate grammar (`source.pion`) for the [Pion](https://github.com/AFK-surf/pion) programming language (`.pion`), maintained in a dedicated minimal repository for [GitHub Linguist](https://github.com/github-linguist/linguist) (`script/add-grammar`).

## Layout

- `syntaxes/pion.tmLanguage.json` — Oniguruma-compatible TextMate grammar (`scopeName: source.pion`, `fileTypes: ["pion"]`)
- `samples/example.pion` — `pionc fmt`-formatted syntax showcase
- `scripts/validate_grammar.py` — schema, regex, regression, and optional compiler parity validator

## Validation

```sh
python3 scripts/validate_grammar.py
# Optional two-way parity check against a local AFK-surf/pion checkout:
python3 scripts/validate_grammar.py --pion-repo /path/to/pion
```

## License

MIT
