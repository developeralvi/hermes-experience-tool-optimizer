# Example: Basic EBTTO plugin

This is a minimal example of a Hermes plugin built on EBTTO's public API.

```python
from hermes_ebtto import register

# EBTTO provides a thin register(cx) entry point.
# The plugin.yaml main field points to the module containing register().
```

## Minimal plugin.yaml

```yaml
name: my-ebtto-plugin
version: 0.1.0
description: A reusable EBTTO plugin
main: my_ebtto_plugin
provides_hooks:
  - pre_tool_call
  - post_tool_call
depends_on: []
```

## Minimal package layout

```
my_ebtto_plugin/
├── __init__.py      # contains register(cx)
└── plugin.yaml      # plugin manifest
```

## Install for local development

```bash
pip install -e ".[dev]"
hermes plugins enable my-ebtto-plugin
```
