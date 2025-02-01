from itertools import chain
from os import listdir, environ
from os.path import isfile, join, dirname
import unittest
from unittest import mock

from AnyQt.QtTest import QTest

from orangecanvas.registry import WidgetRegistry
from orangecanvas.config import EntryPoint
from orangewidget.workflow import widgetsscheme

from Orange.canvas.config import Config
from Orange.canvas import workflows

from Orange.widgets.tests.base import GuiTest
from Orange.widgets.tests.utils import excepthook_catch


def discover_workflows(dir):
    ows_files = [f for f in listdir(dir)
                 if isfile(join(dir, f)) and f.endswith(".ows")]
    for ows_file in ows_files:
        yield join(dir, ows_file)


def registry():
    d = Config.widget_discovery(WidgetRegistry())
    d.run(Config.widgets_entry_points())
    return d.registry


@unittest.skipIf(environ.get("SKIP_EXAMPLE_WORKFLOWS", False),
                 "Example workflows inflate coverage")
class TestWorkflows(GuiTest):
    def test_scheme_examples(self):
        """
        Test if Orange workflow examples can be opened. Examples in canvas
        and also those placed "workflows" subfolder.
        GH-2240
        """
        reg = registry()
        test_workflows = chain(
            discover_workflows(dirname(workflows.__file__)),
            discover_workflows(join(dirname(__file__), "workflows"))
        )
        for ows_file in test_workflows:
            new_scheme = widgetsscheme.WidgetsScheme()
            new_scheme.widget_manager.set_creation_policy(
                new_scheme.widget_manager.Immediate
            )
            new_scheme.signal_manager.pause()
            with open(ows_file, "rb") as f:
                try:
                    with excepthook_catch(raise_on_exit=True):
                        new_scheme.load_from(f, registry=reg)
                except Exception as e:
                    self.fail("Old workflow '{}' could not be loaded\n'{}'".
                              format(ows_file, str(e)))
                finally:
                    new_scheme.clear()
                    new_scheme.deleteLater()
                    del new_scheme
                    QTest.qWait(0)

    def test_examples_order(self):
        ep_first = EntryPoint(
            '!Testname', 'orangecontrib.any_addon.tutorials', '')
        ep_last = EntryPoint(
            'exampletutorials', 'orangecontrib.other_addon.tutorials', '')

        def entry_points(*_, **__):
            return ep_first, ep_last

        with mock.patch("Orange.canvas.config.entry_points", entry_points):
            ep_names = [point.name for point in Config.examples_entry_points()]
        self.assertLess(ep_names.index(ep_first.name),
                        ep_names.index("000-Orange3"))
        self.assertLess(ep_names.index("000-Orange3"),
                        ep_names.index(ep_last.name))
