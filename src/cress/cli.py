"""Typer CLI — the four ``cress`` subcommands.

Thin wrapper over :class:`cress.site.cress`. Each command parses CLI flags,
constructs a ``cress`` instance, and delegates.
"""

import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

import typer

from cress.build_result import BuildResult
from cress.config import load_user_config, resolve_vault
from cress.exceptions import CressError
from cress.post import apply_slug_writebacks, parse_post, plan_slug_writebacks
from cress.reports import BuildWarning
from cress.site import cress
from cress.wikilinks import build_slug_map, substitute_wikilinks

app: typer.Typer = typer.Typer(
    name="cress",
    help="Publish an Obsidian vault to a static HTML blog.",
    no_args_is_help=True,
)


def _resolve_vault_option(vault_opt: Path | None) -> Path:
    user_config = load_user_config()
    return resolve_vault(vault_opt, user_config)


def _json_envelope(
    ok: bool,
    result: dict[str, Any],
    warnings: list[BuildWarning],
    errors: list[BuildWarning],
) -> str:
    payload: dict[str, Any] = {
        "version": 1,
        "ok": ok,
        "result": result,
        "warnings": [asdict(w) for w in warnings],
        "errors": [asdict(e) for e in errors],
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def _build_result_to_dict(result: BuildResult) -> dict[str, Any]:
    return {
        "pages_written": result.pages_written,
        "skipped_posts": result.skipped_posts,
        "duration_ms": result.duration_ms,
    }


@app.command()
def build(
    target: Annotated[
        Path, typer.Option(help="Target product repo (default: current directory).")
    ] = Path("."),
    vault: Annotated[Path | None, typer.Option(help="Obsidian vault root.")] = None,
    drafts_only: Annotated[bool, typer.Option("--drafts-only")] = False,
    no_drafts: Annotated[bool, typer.Option("--no-drafts")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Build the site into the target repo's output directory."""
    try:
        resolved_vault = _resolve_vault_option(vault)
        site = cress(resolved_vault, target)
        result = site.build(drafts_only=drafts_only, no_drafts=no_drafts)
    except CressError as exc:
        # TODO refactor this duplication - 5 places
        # Hard errors: exit non-zero.
        if json_output:
            typer.echo(
                _json_envelope(
                    ok=False,
                    result={},
                    warnings=[],
                    errors=[BuildWarning(type=type(exc).__name__, file="", message=str(exc))],
                )
            )
        else:
            typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    ok = not result.errors
    if json_output:
        typer.echo(
            _json_envelope(
                ok=ok,
                result=_build_result_to_dict(result),
                warnings=result.warnings,
                errors=result.errors,
            )
        )
    else:
        typer.echo(
            f"built {result.pages_written} pages in {result.duration_ms}ms "
            f"({len(result.warnings)} warnings)"
        )
    if not ok:
        raise typer.Exit(code=1)


@app.command()
def validate(
    target: Annotated[
        Path, typer.Option(help="Target product repo (default: current directory).")
    ] = Path("."),
    vault: Annotated[Path | None, typer.Option(help="Obsidian vault root.")] = None,
    fix: Annotated[bool, typer.Option("--fix")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Dry-run parse every post and report issues."""
    try:
        resolved_vault = _resolve_vault_option(vault)
        site = cress(resolved_vault, target)
        issues = _run_validate(site, fix=fix)
    except CressError as exc:
        if json_output:
            typer.echo(
                _json_envelope(
                    ok=False,
                    result={},
                    warnings=[],
                    errors=[BuildWarning(type=type(exc).__name__, file="", message=str(exc))],
                )
            )
        else:
            typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    ok = not issues
    if json_output:
        typer.echo(
            _json_envelope(ok=ok, result={"issues": len(issues)}, warnings=issues, errors=[])
        )
    else:
        if issues:
            for issue in issues:
                typer.echo(f"{issue.type}: {issue.file}: {issue.message}")
        typer.echo(f"{len(issues)} issue(s)")
    if not ok:
        raise typer.Exit(code=1)


@app.command()
def serve(
    target: Annotated[
        Path, typer.Option(help="Target product repo (default: current directory).")
    ] = Path("."),
    vault: Annotated[Path | None, typer.Option(help="Obsidian vault root.")] = None,
    port: Annotated[int, typer.Option(help="Port to bind the dev server.")] = 8000,
    live_reload: Annotated[bool, typer.Option("--live-reload")] = False,
    drafts_only: Annotated[bool, typer.Option("--drafts-only")] = False,
    no_drafts: Annotated[bool, typer.Option("--no-drafts")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Build once, serve the output directory, rebuild on source changes."""
    from cress.server import serve as _serve

    try:
        resolved_vault = _resolve_vault_option(vault)
        site = cress(resolved_vault, target)
    except CressError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    _serve(
        site,
        port=port,
        live_reload=live_reload,
        drafts_only=drafts_only,
        no_drafts=no_drafts,
        json_output=json_output,
    )


@app.command()
def publish(
    target: Annotated[
        Path, typer.Option(help="Target product repo (default: current directory).")
    ] = Path("."),
    vault: Annotated[Path | None, typer.Option(help="Obsidian vault root.")] = None,
    drafts_only: Annotated[bool, typer.Option("--drafts-only")] = False,
    no_drafts: Annotated[bool, typer.Option("--no-drafts")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Build, stage, commit, and optionally push the output directory."""
    from cress.publish import commit_outputs

    try:
        resolved_vault = _resolve_vault_option(vault)
        site = cress(resolved_vault, target)
        result = site.build(drafts_only=drafts_only, no_drafts=no_drafts)
        commit = commit_outputs(
            site.target, site.config.output_dir, site.config, result.pages_written
        )
    except CressError as exc:
        if json_output:
            typer.echo(
                _json_envelope(
                    ok=False,
                    result={},
                    warnings=[],
                    errors=[BuildWarning(type=type(exc).__name__, file="", message=str(exc))],
                )
            )
        else:
            typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    warnings = list(result.warnings)
    if commit.push_error:
        warnings.append(
            BuildWarning(type="git_push_failed", file=str(target), message=commit.push_error)
        )
    envelope: dict[str, Any] = {
        **_build_result_to_dict(result),
        "commit_sha": commit.commit_sha,
        "pushed": commit.pushed,
    }
    if json_output:
        typer.echo(
            _json_envelope(
                ok=not result.errors,
                result=envelope,
                warnings=warnings,
                errors=result.errors,
            )
        )
    else:
        if commit.changed:
            typer.echo(f"committed {commit.commit_sha} ({result.pages_written} pages)")
        else:
            typer.echo("no changes to commit")
        if commit.push_error:
            typer.echo(f"push failed: {commit.push_error}", err=True)
        elif commit.pushed:
            typer.echo("pushed")
    if result.errors:
        raise typer.Exit(code=1)


def _run_validate(site: cress, *, fix: bool) -> list[BuildWarning]:
    """Parse every post, plan slugs, resolve wikilinks — collect issues without writing output."""
    issues: list[BuildWarning] = []
    vault_posts = site.vault / site.config.vault_subfolder
    md_paths = sorted(vault_posts.rglob("*.md"))
    if not md_paths:
        issues.append(
            BuildWarning(type="empty_vault", file=str(vault_posts), message="no posts found")
        )
        return issues

    posts = []
    from cress.exceptions import PostParseError

    for md in md_paths:
        try:
            posts.append(parse_post(md, site.config))
        except PostParseError as exc:
            issues.append(
                BuildWarning(type="post_parse_error", file=str(md), message=str(exc))
            )

    if not posts:
        return issues

    plan = plan_slug_writebacks(posts)
    if plan.duplicates:
        for dup in plan.duplicates:
            issues.append(
                BuildWarning(
                    type="duplicate_slug",
                    file=", ".join(str(p) for p in dup.paths),
                    message=f"slug {dup.slug!r} claimed by multiple posts",
                )
            )
        return issues

    if plan.writebacks:
        if fix:
            apply_slug_writebacks(plan)
            # Re-parse affected posts.
            rewritten = {p for p, _ in plan.writebacks}
            posts = [
                parse_post(p.source_path, site.config) if p.source_path in rewritten else p
                for p in posts
            ]
        else:
            for path, slug in plan.writebacks:
                issues.append(
                    BuildWarning(
                        type="missing_slug",
                        file=str(path),
                        message=f"would generate slug {slug!r} (run with --fix)",
                    )
                )

    # Check wikilinks by running substitution against a render-agnostic body.
    slug_map = build_slug_map(posts)
    wl_warnings: list[BuildWarning] = []
    for post in posts:
        substitute_wikilinks(
            f'<a data-cress-wikilink="{post.body_md}" data-cress-alias=""></a>',
            slug_map,
            [],
            post.source_path,
        )
    issues.extend(wl_warnings)
    return issues


def main() -> None:
    """Console-script entry point registered in ``pyproject.toml``."""
    app()


if __name__ == "__main__":  # pragma: no cover
    main()
