# cress plugins

cress exposes a `plugin` singleton with six decorators. Import it from anywhere in a local plugin file (`<target>/.cress/plugins/*.py`) or from a pip-installed package that registers an entry point in the `cress.plugins` group.

```python
from cress import plugin
```

Every decorator returns the decorated function unchanged, so plugins are just ordinary Python.

## `@plugin.shortcode(name)`

Registers a handler for fenced blocks ```` ```name … ``` ````.

```python
@plugin.shortcode("youtube")
def render_youtube(body: str, **context) -> str:
    import yaml
    cfg = yaml.safe_load(body)
    return f'<iframe src="https://youtube.com/embed/{cfg["id"]}"></iframe>'
```

The body is passed as a string; cress validates it parses as YAML before invoking the handler. The extra `**context` is reserved for future use — accept it so your handler doesn't break when new context is added.

## `@plugin.inline(pattern)`

Adds a custom inline regex for markdown rendering (e.g. `@mentions`).

```python
@plugin.inline(r"@(\w+)")
def render_mention(match, context):
    return f'<a href="/team/{match.group(1)}/">@{match.group(1)}</a>'
```

## `@plugin.template_filter(name)`

Exposes a Django template filter. Registered against every per-build engine instance (new engine per `build()` so filters never leak across builds).

```python
@plugin.template_filter("money")
def money(value):
    return f"${value:,.2f}"
```

Usable in templates: `{{ price|money }}`.

## `@plugin.template_global(name)`

Exposes a Django `simple_tag` named `name`.

```python
@plugin.template_global("build_year")
def build_year():
    import datetime
    return datetime.datetime.now().year
```

Usable in templates: `{% build_year %}`.

## `@plugin.hook(name)`

Attaches to one of four lifecycle events:

| Hook            | When it fires                                           | Arguments           |
| --------------- | ------------------------------------------------------- | ------------------- |
| `before_build`  | Once, after plugin discovery + engine build             | `(config,)`         |
| `after_post`    | Once per rendered post, with the post object            | `(post,)`           |
| `before_write`  | Once with the full `list[OutputFile]` about to be written | `(outputs,)`       |
| `after_build`   | Once, after the manifest writes                         | `(build_result,)`   |

A `before_write` hook that returns a list replaces the output list — useful for minification, injecting `robots.txt`, etc.

## `@plugin.page(path)`

Registers a custom-page generator. The function receives a `PageContext` and should return a `list[OutputFile]`.

```python
@plugin.page("/archive/")
def archive_page(ctx):
    from cress.manifest import OutputFile
    return [OutputFile(relative_path="archive/index.html", content="<h1>Archive</h1>")]
```

## Local vs entry-point plugins

- **Local plugins** live under `<target>/.cress/plugins/*.py`. They are re-exec'd on every `build()`, so `cress serve` picks up edits immediately.
- **Entry-point plugins** are pip-installable packages that declare:

  ```toml
  [project.entry-points."cress.plugins"]
  my_plugin = "my_package.plugin_module"
  ```

  Their top-level `@plugin.*` calls run once per Python process.

**On name collision the local plugin wins** — registered after the entry-point, its handler overwrites the shared one.

## Debugging

Plugin import failures surface as `plugin_load_failed` warnings in the build result rather than crashing the build — check `result.warnings` (or the JSON envelope's `warnings` field) to spot them.
