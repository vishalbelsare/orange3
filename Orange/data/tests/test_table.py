import pickle
import unittest
import os
import warnings

import numpy as np
import scipy.sparse as sp

from Orange.data import (
    ContinuousVariable, DiscreteVariable, StringVariable,
    Domain, Table, IsDefined, FilterContinuous, Values, FilterString,
    FilterDiscrete, FilterStringList, FilterRegex)
from Orange.util import OrangeDeprecationWarning


class TestTableInit(unittest.TestCase):
    def test_empty_table(self):
        t = Table()
        self.assertEqual(t.domain.attributes, ())
        self.assertEqual(t.X.shape, (0, 0))
        self.assertEqual(t.Y.shape, (0, 0))
        self.assertEqual(t.W.shape, (0, 0))
        self.assertEqual(t.metas.shape, (0, 0))
        self.assertEqual(t.ids.shape, (0, ))
        self.assertEqual(t.attributes, {})

    def test_warnings(self):
        domain = Domain([ContinuousVariable("x")])
        self.assertWarns(OrangeDeprecationWarning, Table, domain)
        self.assertWarns(OrangeDeprecationWarning, Table, domain, Table())
        self.assertWarns(OrangeDeprecationWarning, Table, domain, [[12]])
        self.assertWarns(OrangeDeprecationWarning, Table, np.zeros((5, 5)))

    def test_invalid_call_with_kwargs(self):
        self.assertRaises(TypeError, Table, Y=[])
        self.assertRaises(TypeError, Table, "iris", 42)
        self.assertRaises(TypeError, Table, Table(), 42)

    def test_from_numpy(self):
        X = np.arange(20).reshape(5, 4)
        Y = np.arange(5) % 2
        metas = np.array(list("abcde")).reshape(5, 1)
        W = np.arange(5) / 5
        ids = np.arange(100, 105, dtype=int)
        attributes = dict(a=5, b="foo")

        dom = Domain([ContinuousVariable(x) for x in "abcd"],
                     DiscreteVariable("e", values=("no", "yes")),
                     [StringVariable("s")])

        for func in (Table.from_numpy, Table):
            table = func(dom, X, Y, metas, W, attributes, ids)
            np.testing.assert_equal(X, table.X)
            np.testing.assert_equal(Y, table.Y)
            np.testing.assert_equal(metas, table.metas)
            np.testing.assert_equal(W, table.W)
            self.assertEqual(attributes, table.attributes)
            np.testing.assert_equal(ids, table.ids)

            table = func(dom, X, Y, metas, W)
            np.testing.assert_equal(X, table.X)
            np.testing.assert_equal(Y, table.Y)
            np.testing.assert_equal(metas, table.metas)
            np.testing.assert_equal(W, table.W)
            self.assertEqual(ids.shape, (5, ))

            table = func(dom, X, Y, metas)
            np.testing.assert_equal(X, table.X)
            np.testing.assert_equal(Y, table.Y)
            np.testing.assert_equal(metas, table.metas)
            self.assertEqual(table.W.shape, (5, 0))
            self.assertEqual(table.ids.shape, (5, ))

            table = func(Domain(dom.attributes, dom.class_var), X, Y)
            np.testing.assert_equal(X, table.X)
            np.testing.assert_equal(Y, table.Y)
            self.assertEqual(table.metas.shape, (5, 0))
            self.assertEqual(table.W.shape, (5, 0))
            self.assertEqual(table.ids.shape, (5, ))

            table = func(Domain(dom.attributes), X)
            np.testing.assert_equal(X, table.X)
            self.assertEqual(table.Y.shape, (5, 0))
            self.assertEqual(table.metas.shape, (5, 0))
            self.assertEqual(table.W.shape, (5, 0))
            self.assertEqual(table.ids.shape, (5, ))

            self.assertRaises(ValueError, func, dom, X, Y, metas, W[:4])
            self.assertRaises(ValueError, func, dom, X, Y, metas[:4])
            self.assertRaises(ValueError, func, dom, X, Y[:4])

    def test_from_numpy_sparse(self):
        domain = Domain([ContinuousVariable(c) for c in "abc"])
        x = np.arange(12).reshape(4, 3)

        t = Table.from_numpy(domain, x, None, None)
        self.assertFalse(sp.issparse(t.X))

        t = Table.from_numpy(domain, sp.csr_matrix(x))
        self.assertTrue(sp.isspmatrix_csr(t.X))

        t = Table.from_numpy(domain, sp.csc_matrix(x))
        self.assertTrue(sp.isspmatrix_csc(t.X))

        t = Table.from_numpy(domain, sp.coo_matrix(x))
        self.assertTrue(sp.isspmatrix_csr(t.X))

        t = Table.from_numpy(domain, sp.lil_matrix(x))
        self.assertTrue(sp.isspmatrix_csr(t.X))

        t = Table.from_numpy(domain, sp.bsr_matrix(x))
        self.assertTrue(sp.isspmatrix_csr(t.X))

    @staticmethod
    def _new_table(attrs, classes, metas, s):
        def nz(x):  # pylint: disable=invalid-name
            return x if x.size else np.empty((5, 0))

        domain = Domain(attrs, classes, metas)
        X = np.arange(s, s + len(attrs) * 5).reshape(5, -1)
        Y = np.arange(100 + s, 100 + s + len(classes) * 5)
        if len(classes) > 1:
            Y = Y.reshape(5, -1)
        M = np.arange(200 + s, 200 + s + len(metas) * 5).reshape(5, -1)
        return Table.from_numpy(domain, nz(X), nz(Y), nz(M))

    def test_concatenate_horizontal(self):
        a, b, c, d, e, f, g = map(ContinuousVariable, "abcdefg")

        # Common case; one class, no empty's
        tab1 = self._new_table((a, b), (c, ), (d, ), 0)
        tab2 = self._new_table((e, ), (), (f, g), 1000)
        joined = Table.concatenate((tab1, tab2), axis=1)
        domain = joined.domain
        self.assertEqual(domain.attributes, (a, b, e))
        self.assertEqual(domain.class_vars, (c, ))
        self.assertEqual(domain.metas, (d, f, g))
        np.testing.assert_equal(joined.X, np.hstack((tab1.X, tab2.X)))
        np.testing.assert_equal(joined.Y, tab1.Y)
        np.testing.assert_equal(joined.metas, np.hstack((tab1.metas, tab2.metas)))

        # One part of one table is empty
        tab1 = self._new_table((a, b), (), (), 0)
        tab2 = self._new_table((), (), (c, ), 1000)
        joined = Table.concatenate((tab1, tab2), axis=1)
        domain = joined.domain
        self.assertEqual(domain.attributes, (a, b))
        self.assertEqual(domain.class_vars, ())
        self.assertEqual(domain.metas, (c, ))
        np.testing.assert_equal(joined.X, np.hstack((tab1.X, tab2.X)))
        np.testing.assert_equal(joined.metas, np.hstack((tab1.metas, tab2.metas)))

        # Multiple classes, two empty parts are merged
        tab1 = self._new_table((a, b), (c, ), (), 0)
        tab2 = self._new_table((), (d, ), (), 1000)
        joined = Table.concatenate((tab1, tab2), axis=1)
        domain = joined.domain
        self.assertEqual(domain.attributes, (a, b))
        self.assertEqual(domain.class_vars, (c, d))
        self.assertEqual(domain.metas, ())
        np.testing.assert_equal(joined.X, np.hstack((tab1.X, tab2.X)))
        np.testing.assert_equal(joined.Y, np.vstack((tab1.Y, tab2.Y)).T)

        # Merging of attributes and selection of weights
        tab1 = self._new_table((a, b), (c, ), (), 0)
        tab1.attributes = dict(a=5, b=7)
        tab2 = self._new_table((d, ), (e, ), (), 1000)
        with tab2.unlocked():
            tab2.W = np.arange(5)
        tab3 = self._new_table((f, g), (), (), 2000)
        tab3.attributes = dict(a=1, c=4)
        with tab3.unlocked():
            tab3.W = np.arange(5, 10)
        joined = Table.concatenate((tab1, tab2, tab3), axis=1)
        domain = joined.domain
        self.assertEqual(domain.attributes, (a, b, d, f, g))
        self.assertEqual(domain.class_vars, (c, e))
        self.assertEqual(domain.metas, ())
        np.testing.assert_equal(joined.X, np.hstack((tab1.X, tab2.X, tab3.X)))
        np.testing.assert_equal(joined.Y, np.vstack((tab1.Y, tab2.Y)).T)
        self.assertEqual(joined.attributes, dict(a=5, b=7, c=4))
        np.testing.assert_equal(joined.ids, tab1.ids)
        np.testing.assert_equal(joined.W, tab2.W)

        # Raise an exception when no tables are given
        self.assertRaises(ValueError, Table.concatenate, (), axis=1)

    def test_concatenate_invalid_axis(self):
        self.assertRaises(ValueError, Table.concatenate, (), axis=2)

    def test_concatenate_names(self):
        a, b, c, d, e, f, g = map(ContinuousVariable, "abcdefg")

        tab1 = self._new_table((a, ), (c, ), (d, ), 0)
        tab2 = self._new_table((e, ), (), (f, g), 1000)
        tab3 = self._new_table((b, ), (), (), 1000)
        tab2.name = "tab2"
        tab3.name = "tab3"

        joined = Table.concatenate((tab1, tab2, tab3), axis=1)
        self.assertEqual(joined.name, "tab2")

    def test_concatenate_check_domain(self):
        a, b, c, d, e, f = map(ContinuousVariable, "abcdef")
        tables = (self._new_table((a, b), (c, ), (d, e), 5),
                 self._new_table((a, b), (c, ), (d, e), 5),
                 self._new_table((a, b), (f, ), (d, e), 5))

        with self.assertRaises(ValueError):
            Table.concatenate(tables, axis=0)
        Table.concatenate(tables, axis=0, ignore_domains=True)

    def test_with_column(self):
        a, b, c, d, e, f, g = map(ContinuousVariable, "abcdefg")
        col = np.arange(9, 14)
        colr = col.reshape(5, -1)
        tab = self._new_table((a, b, c), (d, ), (e, f), 0)

        # Add to attributes
        tabw = tab.add_column(g, np.arange(9, 14))
        self.assertEqual(tabw.domain.attributes, (a, b, c, g))
        np.testing.assert_equal(tabw.X, np.hstack((tab.X, colr)))
        np.testing.assert_equal(tabw.Y, tab.Y)
        np.testing.assert_equal(tabw.metas, tab.metas)

        # Add to metas
        tabw = tab.add_column(g, np.arange(9, 14), to_metas=True)
        self.assertEqual(tabw.domain.metas, (e, f, g))
        np.testing.assert_equal(tabw.X, tab.X)
        np.testing.assert_equal(tabw.Y, tab.Y)
        np.testing.assert_equal(tabw.metas, np.hstack((tab.metas, colr)))

        # Add to empty attributes
        tab = self._new_table((), (d, ), (e, f), 0)
        tabw = tab.add_column(g, np.arange(9, 14))
        self.assertEqual(tabw.domain.attributes, (g, ))
        np.testing.assert_equal(tabw.X, colr)
        np.testing.assert_equal(tabw.Y, tab.Y)
        np.testing.assert_equal(tabw.metas, tab.metas)

        # Add to empty metas
        tab = self._new_table((a, b, c), (d, ), (), 0)
        tabw = tab.add_column(g, np.arange(9, 14), to_metas=True)
        self.assertEqual(tabw.domain.metas, (g, ))
        np.testing.assert_equal(tabw.X, tab.X)
        np.testing.assert_equal(tabw.Y, tab.Y)
        np.testing.assert_equal(tabw.metas, colr)

        # Pass values as a list
        tab = self._new_table((a, ), (d, ), (e, f), 0)
        tabw = tab.add_column(g, [4, 2, -1, 2, 5])
        self.assertEqual(tabw.domain.attributes, (a, g))
        np.testing.assert_equal(
            tabw.X, np.array([[0, 1, 2, 3, 4], [4, 2, -1, 2, 5]]).T)

        # Add non-primitives as metas; join `float` and `object` to `object`
        tab = self._new_table((a, ), (d, ), (e, f), 0)
        t = StringVariable("t")
        tabw = tab.add_column(t, list("abcde"))
        self.assertEqual(tabw.domain.attributes, (a, ))
        self.assertEqual(tabw.domain.metas, (e, f, t))
        np.testing.assert_equal(
            tabw.metas,
            np.hstack((tab.metas, np.array(list("abcde")).reshape(5, -1))))

    def test_add_column_empty(self):
        a, b = ContinuousVariable("a"), ContinuousVariable("b")
        table = Table.from_list(Domain([a]), [])

        new_table = table.add_column(b, [], to_metas=True)
        self.assertTupleEqual(new_table.domain.attributes, (a,))
        self.assertTupleEqual(new_table.domain.metas, (b,))
        self.assertTupleEqual((0, 1), new_table.X.shape)
        self.assertTupleEqual((0, 1), new_table.metas.shape)

        new_table = table.add_column(ContinuousVariable("b"), [], to_metas=False)
        self.assertTupleEqual(new_table.domain.attributes, (a, b))
        self.assertTupleEqual(new_table.domain.metas, ())
        self.assertTupleEqual((0, 2), new_table.X.shape)
        self.assertTupleEqual((0, 0), new_table.metas.shape)

    def test_copy(self):
        domain = Domain([ContinuousVariable("x")],
                        ContinuousVariable("y"),
                        [ContinuousVariable("z")])
        data1 = Table.from_list(domain, [[1, 2, 3]], weights=[4])
        data1.ids[0]= 5
        data2 = data1.copy()
        with data2.unlocked():
            data2.X += 1
            data2.Y += 1
            data2.metas += 1
            data2.W += 1
            data2.ids += 1
        self.assertEqual(data1.X, [[1]])
        self.assertEqual(data1.Y, [[2]])
        self.assertEqual(data1.metas, [[3]])
        self.assertEqual(data1.W, [[4]])
        self.assertEqual(data1.ids, [[5]])


class TestTableLocking(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.orig_locking = Table.LOCKING
        if os.getenv("CI"):
            assert Table.LOCKING
        else:
            Table.LOCKING = True

    @classmethod
    def tearDownClass(cls):
        Table.LOCKING = cls.orig_locking

    def setUp(self):
        a, b, c, d, e, f, g = map(ContinuousVariable, "abcdefg")
        domain = Domain([a, b, c], d, [e, f])
        self.table = Table.from_numpy(
            domain,
            np.random.random((5, 3)),
            np.random.random(5),
            np.random.random((5, 2)))

    def test_tables_are_locked(self):
        tab = self.table

        with self.assertRaises(ValueError):
            tab.X[0, 0] = 0
        with self.assertRaises(ValueError):
            tab.Y[0] = 0
        with self.assertRaises(ValueError):
            tab.metas[0, 0] = 0
        with self.assertRaises(ValueError):
            tab.W[0] = 0

        with self.assertRaises(ValueError):
            tab.X = np.random.random((5, 3))
        with self.assertRaises(ValueError):
            tab.Y = np.random.random(5)
        with self.assertRaises(ValueError):
            tab.metas = np.random.random((5, 2))
        with self.assertRaises(ValueError):
            tab.W = np.random.random(5)

    def test_unlocking(self):
        tab = self.table
        with tab.unlocked():
            tab.X[0, 0] = 0
            tab.Y[0] = 0
            tab.metas[0, 0] = 0

            tab.X = np.random.random((5, 3))
            tab.Y = np.random.random(5)
            tab.metas = np.random.random((5, 2))
            tab.W = np.random.random(5)

        with tab.unlocked(tab.Y):
            tab.Y[0] = 0
            with self.assertRaises(ValueError):
                tab.X[0, 0] = 0
            with tab.unlocked():
                tab.X[0, 0] = 0
            with self.assertRaises(ValueError):
                tab.X[0, 0] = 0

    def test_force_unlocking(self):
        tab = self.table
        with tab.unlocked():
            tab.Y = np.arange(10)[:5]

        # tab.Y is now a view and can't be unlocked
        with self.assertRaises(ValueError):
            with tab.unlocked(tab.X, tab.Y):
                pass
        # Tets that tab.X was not left unlocked
        with self.assertRaises(ValueError):
            tab.X[0, 0] = 0

        # This is not how force unlocking should be used! Force unlocking is
        # meant primarily for passing tables to Cython code that does not
        # properly define ndarrays as const. They should not modify the table;
        # modification here is meant only for testing.
        with tab.force_unlocked(tab.X, tab.Y):
            tab.X[0, 0] = 0
            tab.Y[0] = 0

    def test_locking_flag(self):
        try:
            default = Table.LOCKING
            Table.LOCKING = False
            self.setUp()
            self.table.X[0, 0] = 0
        finally:
            Table.LOCKING = default

    def test_unpickled_empty_weights(self):
        # ensure that unpickled empty arrays could be unlocked
        self.assertEqual(0, self.table.W.size)
        unpickled = pickle.loads(pickle.dumps(self.table))
        with unpickled.unlocked():
            pass

    def test_unpickling_resets_locks(self):
        default = Table.LOCKING
        try:
            self.setUp()
            pickled_locked = pickle.dumps(self.table)
            Table.LOCKING = False
            tab = pickle.loads(pickled_locked)
            tab.X[0, 0] = 1
            Table.LOCKING = True
            tab = pickle.loads(pickled_locked)
            with self.assertRaises(ValueError):
                tab.X[0, 0] = 1
        finally:
            Table.LOCKING = default

    def test_unpickled_owns_data(self):
        try:
            default = Table.LOCKING
            Table.LOCKING = False
            self.setUp()
            table = self.table
            table.X = table.X.view()
        finally:
            Table.LOCKING = default

        unpickled = pickle.loads(pickle.dumps(table))
        self.assertTrue(all(ar.base is None
                            for ar in (unpickled.X, unpickled.Y, unpickled.W, unpickled.metas)))
        with unpickled.unlocked():
            unpickled.X[0, 0] = 42

    @staticmethod
    def test_unlock_table_derived():
        # pylint: disable=abstract-method
        class ExtendedTable(Table):
            pass

        t = ExtendedTable.from_file("iris")
        with t.unlocked():
            pass


class TestTableFilters(unittest.TestCase):
    def setUp(self):
        self.domain = Domain(
            [ContinuousVariable("c1"),
             ContinuousVariable("c2"),
             DiscreteVariable("d1", values=("a", "b"))],
            ContinuousVariable("y"),
            [ContinuousVariable("c3"),
             DiscreteVariable("d2", values=("c", "d")),
             StringVariable("s1"),
             StringVariable("s2")]
        )
        metas = np.array(
            [0, 1, 0, 1, 1, np.nan, 1] +
            [0, 0, 0, 0, np.nan, 1, 1] +
            "a  b  c  d  e     f    g".split() +
            list("ABCDEF") + [""], dtype=object).reshape(-1, 7).T.copy()
        self.table = Table.from_numpy(
            self.domain,
            np.array(
                [[0, 0, 0],
                 [0, -1, 0],
                 [np.nan, 1, 0],
                 [1, 1, np.nan],
                 [1, 1, 1],
                 [1, 1, 1],
                 [1, 1, 1]]),
            np.array(
                [0, 1, 0, 1, np.nan, 1, 1]),
            metas
        )

    def test_row_filters_is_defined(self):
        filtered = IsDefined()(self.table)
        self.assertEqual(list(filtered.metas[:, -2].flatten()), list("ab"))

        val_filter = Values([
            FilterContinuous(None, FilterContinuous.IsDefined)])
        filtered = val_filter(self.table)
        self.assertEqual(list(filtered.metas[:, -2].flatten()), list("abdg"))

        val_filter = Values([FilterString(None, FilterString.IsDefined)])
        filtered = val_filter(self.table)
        self.assertEqual(list(filtered.metas[:, -2].flatten()), list("abcdef"))

        val_filter = Values([IsDefined()])
        filtered = val_filter(self.table)
        self.assertEqual(list(filtered.metas[:, -2].flatten()), list("ab"))

        val_filter = Values([IsDefined(negate=True)])
        filtered = val_filter(self.table)
        self.assertEqual(list(filtered.metas[:, -2].flatten()), list("cdefg"))

        val_filter = Values([IsDefined(["c1"])])
        filtered = val_filter(self.table)
        self.assertEqual(list(filtered.metas[:, -2].flatten()), list("abdefg"))

        val_filter = Values([IsDefined(["c1"], negate=True)])
        filtered = val_filter(self.table)
        self.assertEqual(list(filtered.metas[:, -2].flatten()), list("c"))

    def test_row_filter_no_discrete(self):
        val_filter = Values([FilterDiscrete(None, "a")])
        self.assertRaises(ValueError, val_filter, self.table)

    def test_row_filter_continuous(self):
        val_filter = Values([
            FilterContinuous(None, FilterContinuous.GreaterEqual, 0)])
        filtered = val_filter(self.table)
        self.assertEqual(list(filtered.metas[:, -2].flatten()), list("adg"))

        val_filter = Values([
            FilterContinuous(None, FilterContinuous.Greater, 0)])
        filtered = val_filter(self.table)
        self.assertEqual(list(filtered.metas[:, -2].flatten()), list("dg"))

        val_filter = Values([
            FilterContinuous(None, FilterContinuous.Less, 1)])
        filtered = val_filter(self.table)
        self.assertEqual(list(filtered.metas[:, -2].flatten()), ["a"])

    def test_row_filter_string(self):
        with self.table.unlocked():
            self.table.metas[:, -1] = self.table.metas[::-1, -2]
        val_filter = Values([
            FilterString(None, FilterString.Between, "c", "e")])
        filtered = val_filter(self.table)
        self.assertEqual(list(filtered.metas[:, -2].flatten()), list("cde"))

    def test_row_stringlist(self):
        val_filter = Values([
            FilterStringList(None, list("bBdDe"))])
        filtered = val_filter(self.table)
        self.assertEqual(list(filtered.metas[:, -2].flatten()), list("bd"))

        val_filter = Values([
            FilterStringList(None, list("bDe"), case_sensitive=False)])
        filtered = val_filter(self.table)
        self.assertEqual(list(filtered.metas[:, -2].flatten()), list("bde"))

    def test_row_stringregex(self):
        val_filter = Values([FilterRegex(None, "[bBdDe]")])
        filtered = val_filter(self.table)
        self.assertEqual(list(filtered.metas[:, -2].flatten()), list("bd"))

    def test_is_defined(self):
        val_filter = IsDefined(columns=["c3"])
        filtered = val_filter(self.table)
        self.assertEqual(list(filtered.metas[:, -2].flatten()), list("abcdeg"))


class TableColumnViewTests(unittest.TestCase):
    def setUp(self) -> None:
        y = ContinuousVariable("y")
        d = DiscreteVariable("d", values=("a", "b"))
        t = ContinuousVariable("t")
        m = StringVariable("m")
        self.data = Table.from_numpy(
            Domain([y, d], t, [m]),
            np.array([[1, 2, 3], [0, 0, 1]]).T,
            np.array([100, 200, 200]),
            np.array(["abc def ghi".split()]).T
        )
        self.y2 = ContinuousVariable(
            "y2", compute_value=lambda data: 2 * data[:, y].X[:, 0])


class TestTableGetColumn(TableColumnViewTests):
    def test_get_column_proper_view(self):
        data, y = self.data, self.data.domain["y"]

        col = data.get_column(y)
        np.testing.assert_equal(col, data.X[:, 0])
        self.assertIs(col.base, data.X)

        col = data.get_column(y, copy=True)
        np.testing.assert_equal(col, data.X[:, 0])
        self.assertIsNone(col.base)

    def test_get_column_computed(self):
        data, y2 = self.data, self.y2

        col2 = data.get_column(y2)
        np.testing.assert_equal(col2, [2, 4, 6])
        self.assertIsNone(col2.base)

        col2 = data.get_column(y2, copy=True)
        np.testing.assert_equal(col2, [2, 4, 6])
        self.assertIsNone(col2.base)

    def test_get_column_discrete(self):
        data, d = self.data, self.data.domain["d"]

        col = data.get_column(d)
        np.testing.assert_equal(col, [0, 0, 1])
        self.assertIs(col.base, data.X)

        col = data.get_column(d, copy=True)
        np.testing.assert_equal(col, [0, 0, 1])
        self.assertIsNone(col.base)

        e = DiscreteVariable("d", values=("a", "b"))
        assert e == d
        col = data.get_column(e)
        np.testing.assert_equal(col, [0, 0, 1])
        self.assertIs(col.base, data.X)

        e = DiscreteVariable("d", values=("a", "b", "c"))
        assert e == d  # because that's how Variable mapping works
        col = data.get_column(e)
        np.testing.assert_equal(col, [0, 0, 1])

        e = DiscreteVariable("d", values=("a", "c", "b"))
        assert e == d  # because that's how Variable mapping works
        col = data.get_column(e)
        np.testing.assert_equal(col, [0, 0, 2])

        with data.unlocked(data.X):
            data.X = sp.csr_matrix(data.X)
        e = DiscreteVariable("d", values=("a", "c", "b"))
        assert e == d  # because that's how Variable mapping works
        col = data.get_column(e)
        np.testing.assert_equal(col, [0, 0, 2])


    def test_sparse(self):
        data, y = self.data, self.data.domain["y"]
        with data.unlocked(data.X):
            orig_y = data.X[:, 0]
            data.X = sp.csr_matrix(data.X)

        col = data.get_column(y)
        self.assertFalse(sp.issparse(col))
        np.testing.assert_equal(col, orig_y)

        col = data.get_column(y, copy=True)
        self.assertFalse(sp.issparse(col))
        np.testing.assert_equal(col, orig_y)

    def test_get_column_no_variable(self):
        self.assertRaises(ValueError, self.data.get_column,
                          ContinuousVariable("y3"))

    def test_index_by_int(self):
        data = self.data

        col = data.get_column(0)
        np.testing.assert_equal(col, data.X[:, 0])
        self.assertIs(col.base, data.X)

        col = data.get_column(0, copy=True)
        np.testing.assert_equal(col, data.X[:, 0])
        self.assertIsNone(col.base)

        col = data.get_column(2)
        np.testing.assert_equal(col, data.Y)
        self.assertIs(col, data.Y)

        col = data.get_column(-1)
        np.testing.assert_equal(col, data.metas[:, 0])
        self.assertIs(col.base, data.metas)

    def test_index_by_str(self):
        data = self.data

        col = data.get_column("y")
        np.testing.assert_equal(col, data.X[:, 0])
        self.assertIs(col.base, data.X)

        col = data.get_column("y", copy=True)
        np.testing.assert_equal(col, data.X[:, 0])
        self.assertIsNone(col.base)

        col = data.get_column("t")
        np.testing.assert_equal(col, data.Y)
        self.assertIs(col, data.Y)

        col = data.get_column("m")
        np.testing.assert_equal(col, data.metas[:, 0])
        self.assertIs(col.base, data.metas)


class TestTableGetColumnView(TableColumnViewTests):
    def test_get_column_view_by_var(self):
        data = self.data

        with self.assertWarns(OrangeDeprecationWarning):
            col, sparse = data.get_column_view(self.data.domain["y"])
        np.testing.assert_equal(col, data.X[:, 0])
        self.assertFalse(sparse)

        with self.assertWarns(OrangeDeprecationWarning):
            col, sparse = data.get_column_view(self.data.domain["t"])
        np.testing.assert_equal(col, data.Y)
        self.assertFalse(sparse)

        with self.assertWarns(OrangeDeprecationWarning):
            col, sparse = data.get_column_view(self.data.domain["m"])
        np.testing.assert_equal(col, data.metas[:, 0])
        self.assertFalse(sparse)

        with self.assertWarns(OrangeDeprecationWarning):
            self.assertRaises(ValueError, data.get_column_view, self.y2)

    def test_get_column_view_by_name(self):
        data = self.data

        with self.assertWarns(OrangeDeprecationWarning):
            col, sparse = data.get_column_view("y")
        np.testing.assert_equal(col, data.X[:, 0])
        self.assertFalse(sparse)

        with self.assertWarns(OrangeDeprecationWarning):
            col, sparse = data.get_column_view("t")
        np.testing.assert_equal(col, data.Y)
        self.assertFalse(sparse)

        with self.assertWarns(OrangeDeprecationWarning):
            col, sparse = data.get_column_view("m")
        np.testing.assert_equal(col, data.metas[:, 0])
        self.assertFalse(sparse)

        with self.assertWarns(OrangeDeprecationWarning):
            self.assertRaises(ValueError, data.get_column_view, "y2")

    def test_get_column_view_by_index(self):
        data = self.data

        with self.assertWarns(OrangeDeprecationWarning):
            col, sparse = data.get_column_view(0)
        np.testing.assert_equal(col, data.X[:, 0])
        self.assertFalse(sparse)

        with self.assertWarns(OrangeDeprecationWarning):
            col, sparse = data.get_column_view(2)
        np.testing.assert_equal(col, data.Y)
        self.assertFalse(sparse)

        with self.assertWarns(OrangeDeprecationWarning):
            col, sparse = data.get_column_view(-1)
        np.testing.assert_equal(col, data.metas[:, 0])
        self.assertFalse(sparse)

        with self.assertWarns(OrangeDeprecationWarning):
            self.assertRaises(ValueError, data.get_column_view, "y2")

    def test_sparse(self):
        warnings.simplefilter("ignore", OrangeDeprecationWarning)

        data, y = self.data, self.data.domain["y"]
        with data.unlocked(data.X):
            orig_y = data.X[:, 0]
            data.X = sp.csr_matrix(data.X)

        # self.assertWarns does not work with multiple warnings
        warnings.filterwarnings("error", ".*dense copy.*")
        self.assertRaises(UserWarning, data.get_column_view, y)

        warnings.filterwarnings("ignore", ".*dense copy.*")
        col, sparse = data.get_column_view(y)
        np.testing.assert_equal(col, orig_y)
        self.assertTrue(sparse)

    def test_mapped(self):
        warnings.simplefilter("ignore", OrangeDeprecationWarning)
        data, d = self.data, self.data.domain["d"]

        e = DiscreteVariable("d", values=("a", "b"))
        assert e == d
        col, _ = data.get_column_view(e)
        np.testing.assert_equal(col, [0, 0, 1])

        e = DiscreteVariable("d", values=("a", "b", "c"))
        assert e == d  # because that's how Variable mapping works
        warnings.filterwarnings("error", ".*mapped copy.*")
        self.assertRaises(UserWarning, data.get_column_view, e)

        warnings.filterwarnings("ignore", ".*mapped copy.*")
        col, _ = data.get_column_view(e)
        np.testing.assert_equal(col, [0, 0, 1])

        e = DiscreteVariable("d", values=("a", "c", "b"))
        assert e == d  # because that's how Variable mapping works
        col, _ = data.get_column_view(e)
        np.testing.assert_equal(col, [0, 0, 2])

    def test_meta_is_float(self):
        data = Table.from_list(
            Domain([], None, [ContinuousVariable("x"),
                              DiscreteVariable("y", values=["a", "b"])]),
            [[0, 0]])
        self.assertEqual(data.get_column("x").dtype, float)
        self.assertEqual(data.get_column("y").dtype, float)



if __name__ == "__main__":
    unittest.main()
