# Repository Guidelines

## Project Structure & Module Organization

This workspace currently contains no application source, tests, assets, or project manifests. The only existing entries are `.agents/`, `.codex/`, and `.git/`; treat these as workspace metadata rather than source directories.

When adding the initial implementation, group related modules by responsibility and document their locations in `README.md`. Keep tests separate from generated outputs. Introduce directories such as `src/`, `tests/`, and `docs/` only when their contents are needed.

## Build, Test, and Development Commands

No build, test, lint, or local-run commands are configured yet. Do not assume commands such as `npm test` or `make build` work.

When selecting a toolchain, add its dependency manifest and document exact setup, execution, and validation commands in `README.md`. Prefer reproducible dependency versions and commands that run from the repository root.

## Coding Style & Naming Conventions

No language-specific style or formatter is established. Follow the conventions of the language introduced, use consistent indentation within each file, and choose descriptive module and function names. Add formatter or linter configuration alongside the first implementation so contributors can reproduce checks.

## Testing Guidelines

No testing framework or coverage threshold exists. Add tests for new behavior and bug fixes using the chosen language’s standard tooling. Name tests after the behavior they verify and document the command required to run them. Keep test fixtures small and deterministic.

## Commit & Pull Request Guidelines

Git history is unavailable in this workspace, so no existing commit convention can be verified. Use concise, imperative commit subjects, such as `Add evaluation runner`.

Pull requests should explain the change, its motivation, and validation performed. Link related issues when available and identify any setup changes or untested behavior.

## Security & Configuration

Keep credentials, local environment files, and large generated artifacts out of version control. Document required configuration using placeholder values rather than real secrets.
