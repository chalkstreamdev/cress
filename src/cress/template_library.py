"""Shared Django template ``Library`` for cress plugins.

``build_engine`` registers this module as a ``builtins`` for every Engine
it constructs, so plugin-registered filters and globals (``simple_tag``) are
available in every template without an explicit ``{% load %}`` tag.

A single :class:`~django.template.Library` instance lives on this module.
``install_plugin_registrations`` clears any previous registrations and
re-applies the current :class:`~cress.plugins.PluginRegistry`. Because a
fresh Engine is built each ``build()``, plugin filter/global hot-reload
is automatic — stale registrations die with the old Engine instance.
"""

from django.template import Library

from cress.plugins import PluginRegistry

register: Library = Library()


def install_plugin_registrations(registry: PluginRegistry) -> None:
    """Reset the shared Library and apply ``registry``'s filters + globals."""
    register.filters.clear()
    register.tags.clear()
    for name, fn in registry.template_filters.items():
        register.filter(name, fn)
    for name, fn in registry.template_globals.items():
        register.simple_tag(fn, name=name)
