import hermes_cli.plugins as p
import inspect
print("=== Module attrs ===")
for name in dir(p):
    if not name.startswith('_'):
        obj = getattr(p, name)
        if inspect.isclass(obj) or inspect.isfunction(obj):
            print(f"  {name}: {obj}")
print()
print("=== PluginContext methods ===")
import hermes_cli.plugins
import inspect
for name in dir(hermes_cli.plugins.PluginContext):
    if not name.startswith('_'):
        obj = getattr(hermes_cli.plugins.PluginContext, name)
        if inspect.isfunction(obj) or inspect.ismethod(obj):
            try:
                sig = inspect.signature(obj)
                print(f"  {name}{sig}")
            except Exception:
                print(f"  {name}()")
print()
print("=== PluginManifest attrs ===")
for name in dir(hermes_cli.plugins.PluginManifest):
    if not name.startswith('_'):
        print(f"  {name}")
print()
print("=== Hook-like constants ===")
for name in dir(hermes_cli.plugins):
    if 'hook' in name.lower() or 'lifecycle' in name.lower():
        print(f"  {name}")
