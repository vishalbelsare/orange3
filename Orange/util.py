"""Various small utilities that might be useful everywhere"""
import logging
import os
import time
import inspect
import datetime
import math
import functools
import importlib.resources
from contextlib import contextmanager
from importlib.metadata import distribution
from typing import TYPE_CHECKING, Callable, Union, Optional
from weakref import WeakKeyDictionary
from enum import Enum as _Enum
from functools import wraps, partial
from operator import attrgetter
from itertools import chain, count, repeat

from collections import namedtuple
import warnings

# Exposed here for convenience. Prefer patching to try-finally blocks
from unittest.mock import patch  # pylint: disable=unused-import

import numpy as np

# Backwards-compat
from Orange.data.util import scale  # pylint: disable=unused-import

if TYPE_CHECKING:
    from numpy.typing import DTypeLike


log = logging.getLogger(__name__)


class OrangeWarning(UserWarning):
    pass


class OrangeDeprecationWarning(OrangeWarning, DeprecationWarning):
    pass


warnings.simplefilter('default', OrangeWarning)

if os.environ.get('ORANGE_DEPRECATIONS_ERROR'):
    warnings.simplefilter('error', OrangeDeprecationWarning)


def _log_warning(msg):
    """
    Replacement for `warnings._showwarnmsg_impl` that logs the warning
    Logs the warning in the appropriate list, or passes it to the original
    function if the warning wasn't issued within the log_warnings context.
    """
    for frame in inspect.stack():
        if frame.frame in warning_loggers:
            warning_loggers[frame.frame].append(msg)
            break
    else:
        __orig_showwarnmsg_impl(msg)


@contextmanager
def log_warnings():
    """
    logs all warnings that occur within context, including warnings from calls.

    ```python
    with log_warnings() as warnings:
       ...
    ```

    Unlike `warnings.catch_warnings(record=True)`, this manager is thread-safe
    and will only log warning from this thread. It does so by storing the
    stack frame within which the context is created, and then checking the
    stack when the warning is issued.

    Nesting of `log_warnings` within the same function will raise an error.
    If `log_wanings` are nested within function calls, the warning is logged
    in the inner-most context.

    If `catch_warnings` is used within the `log_warnings` context, logging is
    disabled until the `catch_warnings` exits. This looks inevitable (without
    patching `catch_warnings`, which I'd prefer not to do).

    If `catch_warnings` is used outside this context, everything, including
    warning filtering, should work as expected.

    Note: the method imitates `catch_warnings` by patching the `warnings`
    module's internal function `_showwarnmsg_impl`. Python (as of version 3.9)
    doesn't seem to offer any other way of catching the warnings. This function
    was introduced in Python 3.6, so we cover all supported versions. If it is
    ever removed, unittests will crash, so we'll know. :)
    """
    # currentframe().f_back is `contextmanager`'s __enter__
    frame = inspect.currentframe().f_back.f_back
    if frame in warning_loggers:
        raise ValueError("nested log_warnings")
    try:
        warning_loggers[frame] = []
        yield warning_loggers[frame]
    finally:
        del warning_loggers[frame]


# pylint: disable=protected-access
warning_loggers = {}
__orig_showwarnmsg_impl = warnings._showwarnmsg_impl
warnings._showwarnmsg_impl = _log_warning


def resource_filename(path):
    """
    Return the resource filename path relative to the Orange package.
    """
    path = importlib.resources.files("Orange").joinpath(path)
    return str(path)


def get_entry_point(dist, group, name):
    """
    Load and return the entry point from the distribution.
    """
    dist = distribution(dist)
    eps = dist.entry_points.select(group=group, name=name)
    ep = next(iter(eps))
    return ep.load()


def deprecated(obj):
    """
    Decorator. Mark called object deprecated.

    Parameters
    ----------
    obj: callable or str
        If callable, it is marked as deprecated and its calling raises
        OrangeDeprecationWarning. If str, it is the alternative to be used
        instead of the decorated function.

    Returns
    -------
    f: wrapped callable or decorator
        Returns decorator if obj was str.

    Examples
    --------
    >>> @deprecated
    ... def old():
    ...     return 'old behavior'
    >>> old()  # doctest: +SKIP
    /... OrangeDeprecationWarning: Call to deprecated ... old ...
    'old behavior'

    >>> class C:
    ...     @deprecated('C.new()')
    ...     def old(self):
    ...         return 'old behavior'
    ...     def new(self):
    ...         return 'new behavior'
    >>> C().old() # doctest: +SKIP
    /... OrangeDeprecationWarning: Call to deprecated ... C.old ...
      use use C.new() instead ...
    'old behavior'
    """
    alternative = f'; use {obj} instead' if isinstance(obj, str) else ''

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            name = func.__name__
            if hasattr(func, "__self__"):
                name = f'{func.__self__.__class__}.{name}'
            warnings.warn(f'Call to deprecated {name}{alternative}',
                          OrangeDeprecationWarning, stacklevel=2)
            return func(*args, **kwargs)
        return wrapper

    return decorator if alternative else decorator(obj)


# This should look like decorator, not a class, pylint: disable=invalid-name
class allot:
    """
    Decorator that allows a function only a specified portion of time per call.

    Usage:

    ```
    @allot(0.2, overflow=of)
    def f(x):
       ...
    ```

    The above function is allotted 0.2 second per second. If it runs for 0.2 s,
    all subsequent calls in the next second (after the start of the call) are
    ignored. If it runs for 0.1 s, subsequent calls in the next 0.5 s are
    ignored. If it runs for a second, subsequent calls are ignored for 5 s.

    An optional overflow function can be given as a keyword argument
    `overflow`. This function must have the same signature as the wrapped
    function and is called instead of the original when the call is blocked.

    If the overflow function is not given, the wrapped function must not return
    result. This is because without the overflow function, the wrapper has no
    value to return when the call is skipped.

    The decorator adds a method `call` to force the call, e.g. by calling
    f.call(5), in the above case. The used up time still counts for the
    following (non-forced) calls.

    The decorator also adds two attributes:

    - f.last_call_duration is the duration of the last call (in seconds)
    - f.no_call_before contains the time stamp when the next call will be made.

    The decorator can be used for functions and for methods.

    A non-parametrized decorator doesn't block any calls and only adds
    last_call_duration, so that it can be used for timing.
    """

    try:
        __timer = time.thread_time
    except AttributeError:
        # thread_time is not available on macOS
        __timer = time.process_time

    def __new__(cls: type, arg: Union[None, float, Callable], *,
                overflow: Optional[Callable] = None,
                _bound_methods: Optional[WeakKeyDictionary] = None):
        self = super().__new__(cls)

        if arg is None or isinstance(arg, float):
            # Parametrized decorator
            if arg is not None:
                assert arg > 0

            def set_func(func):
                self.__init__(func,
                              overflow=overflow,
                              _bound_methods=_bound_methods)
                self.allotted_time = arg
                return self

            return set_func

        else:
            # Non-parametrized decorator
            self.allotted_time = None
            return self

    def __init__(self,
                 func: Callable, *,
                 overflow: Optional[Callable] = None,
                 _bound_methods: Optional[WeakKeyDictionary] = None):
        assert callable(func)
        self.func = func
        self.overflow = overflow
        functools.update_wrapper(self, func)

        self.no_call_before = 0
        self.last_call_duration = None

        # Used by __get__; see a comment there
        if _bound_methods is None:
            self.__bound_methods = WeakKeyDictionary()
        else:
            self.__bound_methods = _bound_methods

    # If we are wrapping a method, __get__ is called to bind it.
    # Create a wrapper for each instance and store it, so that each instance's
    # method gets its share of time.
    def __get__(self, inst, cls):
        if inst is None:
            return self

        if inst not in self.__bound_methods:
            # __bound_methods caches bound methods per instance. This is not
            # done for perfoamnce. Bound methods can be rebound, even to
            # different instances or even classes, e.g.
            # >>> x = f.__get__(a, A)
            # >>> y = x.__get__(b, B)
            # >>> z = x.__get__(a, A)
            # After this, we want `x is z`, there shared caching. This looks
            # bizarre, but let's keep it safe. At least binding to the same
            # instance, f.__get__(a, A),__get__(a, A), sounds reasonably
            # possible.
            cls = type(self)
            bound_overflow = self.overflow and self.overflow.__get__(inst, cls)
            decorator = cls(
                self.allotted_time,
                overflow=bound_overflow,
                _bound_methods=self.__bound_methods)
            self.__bound_methods[inst] = decorator(self.func.__get__(inst, cls))

        return self.__bound_methods[inst]

    def __call__(self, *args, **kwargs):
        if self.__timer() < self.no_call_before:
            if self.overflow is None:
                return None
            return self.overflow(*args, **kwargs)
        return self.call(*args, **kwargs)

    def call(self, *args, **kwargs):
        start = self.__timer()
        result = self.func(*args, **kwargs)
        self.last_call_duration = self.__timer() - start
        if self.allotted_time is not None:
            if self.overflow is None:
                assert result is None, "skippable function cannot return a result"
            self.no_call_before = start + self.last_call_duration / self.allotted_time
        return result


def literal_eval(literal):
    import ast  # pylint: disable=import-outside-toplevel
    # ast.literal_eval does not parse empty set ¯\_(ツ)_/¯

    if literal == "set()":
        return set()
    return ast.literal_eval(literal)


op_map = {
    '==': lambda a, b: a == b,
    '>=': lambda a, b: a >= b,
    '<=': lambda a, b: a <= b,
    '>': lambda a, b: a > b,
    '<': lambda a, b: a < b
}


_Requirement = namedtuple("_Requirement", ["name", "op", "value"])


bool_map = {
    "True": True,
    "true": True,
    1: True,
    "False": False,
    "false": False,
    0: False
}


def requirementsSatisfied(required_state, local_state, req_type=None):
    """
    Checks a list of requirements against a dictionary representing local state.

    Args:
        required_state ([str]): List of strings representing required state
                                using comparison operators
        local_state (dict): Dictionary representing current state
        req_type (type): Casts values to req_type before comparing them.
                         Defaults to local_state type.
    """
    for req_string in required_state:
        # parse requirement
        req = None
        for op_str, op in op_map.items():
            split = req_string.split(op_str)
            # if operation is not in req_string, continue
            if len(split) == 2:
                req = _Requirement(split[0], op, split[1])
                break

        if req is None:
            log.error("Invalid requirement specification: %s", req_string)
            return False

        compare_type = req_type or type(local_state[req.name])
        # check if local state satisfies required state (specification)
        if compare_type is bool:
            # boolean is a special case, where simply casting to bool does not produce target result
            required_value = bool_map[req.value]
        else:
            required_value = compare_type(req.value)
        local_value = compare_type(local_state[req.name])

        # finally, compare the values
        if not req.op(local_value, required_value):
            return False
    return True


def try_(func, default=None):
    """Try return the result of func, else return default."""
    try:
        return func()
    except Exception:  # pylint: disable=broad-except
        return default


def flatten(lst):
    """Flatten iterable a single level."""
    return chain.from_iterable(lst)


class Registry(type):
    """Metaclass that registers subtypes."""
    def __new__(mcs, name, bases, attrs):
        cls = type.__new__(mcs, name, bases, attrs)
        if not hasattr(cls, 'registry'):
            cls.registry = {}
        else:
            cls.registry[name] = cls
        return cls

    def __iter__(cls):
        return iter(cls.registry)

    def __str__(cls):
        if cls in cls.registry.values():
            return cls.__name__
        return f'{cls.__name__}({{{", ".join(cls.registry)}}})'


# it is what it is, we keep for compatibility:
# pylint: disable=keyword-arg-before-vararg
def namegen(prefix='_', *args, spec_count=count, **kwargs):
    """Continually generate names with `prefix`, e.g. '_1', '_2', ..."""
    # pylint: disable=stop-iteration-return
    spec_count = iter(spec_count(*args, **kwargs))
    while True:
        yield prefix + str(next(spec_count))


def export_globals(globals, module_name):
    """
    Return list of important for export globals (callables, constants) from
    `globals` dict, defined in module `module_name`.

    Usage
    -----
    In some module, on the second-to-last line:

    __all__ = export_globals(globals(), __name__)

    """
    return [getattr(v, '__name__', k)
            for k, v in globals.items()                          # export
            if ((callable(v) and v.__module__ == module_name     # callables from this module
                 or k.isupper()) and                             # or CONSTANTS
                not getattr(v, '__name__', k).startswith('_'))]  # neither marked internal


_NOTSET = object()


def deepgetattr(obj, attr, default=_NOTSET):
    """Works exactly like getattr(), except that attr can be a nested attribute
    (e.g. "attr1.attr2.attr3").
    """
    try:
        return attrgetter(attr)(obj)
    except AttributeError:
        if default is _NOTSET:
            raise
        return default


def color_to_hex(color):
    # pylint: disable=consider-using-f-string
    return "#{:02X}{:02X}{:02X}".format(*color)


def hex_to_color(s):
    return int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16)


def inherit_docstrings(cls):
    """Inherit methods' docstrings from first superclass that defines them"""
    for method in cls.__dict__.values():
        if inspect.isfunction(method) and method.__doc__ is None:
            for parent in cls.__mro__[1:]:
                doc = getattr(parent, method.__name__, None).__doc__
                if doc:
                    method.__doc__ = doc
                    break
    return cls


class Enum(_Enum):
    """Enum that represents itself with the qualified name, e.g. Color.red"""
    __repr__ = _Enum.__str__


def interleave(seq1, seq2):
    """
    Interleave elements of `seq2` between consecutive elements of `seq1`.

    Example
    -------
    >>> list(interleave([1, 3, 5], [2, 4]))
    [1, 2, 3, 4, 5]
    >>> list(interleave([1, 2, 3, 4], repeat("<")))
    [1, '<', 2, '<', 3, '<', 4]
    """
    iterator1, iterator2 = iter(seq1), iter(seq2)
    try:
        leading = next(iterator1)
    except StopIteration:
        pass
    else:
        for element in iterator1:
            yield leading
            try:
                yield next(iterator2)
            except StopIteration:
                return
            leading = element
        yield leading


def Reprable_repr_pretty(name, itemsiter, printer, cycle):
    # type: (str, Iterable[Tuple[str, Any]], Ipython.lib.pretty.PrettyPrinter, bool) -> None
    if cycle:
        printer.text(f"{name}(...)")
    else:
        def printitem(field, value):
            printer.text(field + "=")
            printer.pretty(value)

        def printsep():
            printer.text(",")
            printer.breakable()

        itemsiter = (partial(printitem, *item) for item in itemsiter)
        sepiter = repeat(printsep)

        with printer.group(len(name) + 1, f"{name}(", ")"):
            for part in interleave(itemsiter, sepiter):
                part()
                part()


class _Undef:
    def __repr__(self):
        return "<?>"
_undef = _Undef()


class Reprable:
    """A type that inherits from this class has its __repr__ string
    auto-generated so that it "[...] should look like a valid Python
    expression that could be used to recreate an object with the same
    value [...]" (see See Also section below).

    This relies on the instances of type to have attributes that
    match the arguments of the type's constructor. Only the values that
    don't match the arguments' defaults are printed, i.e.:

        >>> class C(Reprable):
        ...     def __init__(self, a, b=2):
        ...         self.a = a
        ...         self.b = b
        >>> C(1, 2)
        C(a=1)
        >>> C(1, 3)
        C(a=1, b=3)

    If Reprable instances define `_reprable_module`, that string is used
    as a fully-qualified module name and is printed. `_reprable_module`
    can also be True in which case the type's home module is used.

        >>> class C(Reprable):
        ...     _reprable_module = True
        >>> C()
        Orange.util.C()
        >>> class C(Reprable):
        ...     _reprable_module = 'something_else'
        >>> C()
        something_else.C()
        >>> class C(Reprable):
        ...     class ModuleResolver:
        ...         def __str__(self):
        ...             return 'magic'
        ...     _reprable_module = ModuleResolver()
        >>> C()
        magic.C()

    See Also
    --------
    https://docs.python.org/3/reference/datamodel.html#object.__repr__
    """
    _reprable_module = ''

    def _reprable_fields(self):
        # type: () -> Iterable[Tuple[str, Any]]
        cls = self.__class__
        sig = inspect.signature(cls.__init__)
        for param in sig.parameters.values():
            # Skip self, *args, **kwargs
            if param.name != 'self' and \
                    param.kind not in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
                yield param.name, param.default

    # pylint: disable=unused-argument
    def _reprable_omit_param(self, name, default, value):
        if default is value:
            return True
        if type(default) is type(value):
            try:
                return default == value
            except (ValueError, TypeError):
                return False
        else:
            return False

    def _reprable_items(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            warnings.simplefilter("error", PendingDeprecationWarning)
            for name, default in self._reprable_fields():
                try:
                    value = getattr(self, name)
                except (DeprecationWarning, PendingDeprecationWarning):
                    continue
                except AttributeError:
                    value = _undef
                if not self._reprable_omit_param(name, default, value):
                    yield name, default, value

    def _repr_pretty_(self, p, cycle):
        """IPython pretty print hook."""
        module = self._reprable_module
        if module is True:
            module = self.__class__.__module__

        nameparts = (([str(module)] if module else []) +
                     [self.__class__.__name__])
        name = ".".join(nameparts)
        Reprable_repr_pretty(
            name, ((f, v) for f, _, v in self._reprable_items()),
            p, cycle)

    def __repr__(self):
        module = self._reprable_module
        if module is True:
            module = self.__class__.__module__
        nameparts = (([str(module)] if module else []) +
                     [self.__class__.__name__])
        name = ".".join(nameparts)
        items = ", ".join(f"{f}={repr(v)}"
                          for f, _, v in self._reprable_items())
        return f"{name}({items})"


def wrap_callback(progress_callback, start=0, end=1):
    """
    Wraps a progress callback function to allocate it end-start proportion
    of an execution time.

    :param progress_callback: callable
    :param start: float
    :param end: float
    :return: callable
    """
    @wraps(progress_callback)
    def func(progress, *args, **kwargs):
        adjusted_progress = start + progress * (end - start)
        return progress_callback(adjusted_progress, *args, **kwargs)
    return func


def dummy_callback(*_, **__):
    """ A dummy callable. """
    return 1


def utc_from_timestamp(timestamp) -> datetime.datetime:
    """
    Return the UTC datetime corresponding to the POSIX timestamp.
    """
    return datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc) + \
           datetime.timedelta(seconds=float(timestamp))


def frompyfunc(func: Callable, nin: int, nout: int, dtype: 'DTypeLike'):
    """
    Wrap an `func` callable into an ufunc-like function with `out`, `dtype`,
    `where`, ... parameters. The `dtype` is used as the default.

    Unlike numpy.frompyfunc this function always returns output array of
    the specified `dtype`. Note that the conversion is space efficient.
    """
    func_ = np.frompyfunc(func, nin, nout)

    @wraps(func)
    def funcv(*args, out=None, dtype=dtype, casting="unsafe", **kwargs):
        if not args:
            raise TypeError
        args = [np.asanyarray(a) for a in args]
        args = np.broadcast_arrays(*args)
        shape = args[0].shape
        have_out = out is not None
        if out is None and dtype is not None:
            out = np.empty(shape, dtype)

        res = func_(*args, out, dtype=dtype, casting=casting, **kwargs)
        if res.shape == () and not have_out:
            return res.item()
        else:
            return res

    return funcv


_isnan = math.isnan


def nan_eq(a, b) -> bool:
    """
    Same as `a == b` except where both `a` and `b` are  NaN values in which
    case `True` is returned.

    .. seealso:: nan_hash_stand
    """
    try:
        both_nan = _isnan(a) and _isnan(b)
    except TypeError:
        return a == b
    else:
        return both_nan or a == b


def nan_hash_stand(value):
    """
    If `value` is a NaN then return a singular global *standin* NaN instance,
    otherwise return `value` unchanged.

    Use this where a hash of `value` is needed and `value` might be a NaN
    to account for distinct hashes of NaN instances.

    E.g. the folowing `__eq__` and `__hash__` pairs would be ill-defined for
    `A(float("nan"))` instances if `nan_hash_stand` and `nan_eq` were not
    used.
    >>> class A:
    ...     def __init__(self, v): self.v = v
    ...     def __hash__(self): return hash(nan_hash_stand(self.v))
    ...     def __eq__(self, other): return nan_eq(self.v, other.v)
    """
    try:
        if _isnan(value):
            return math.nan
    except TypeError:
        pass
    return value


# For best result, keep this at the bottom
__all__ = export_globals(globals(), __name__)

# ONLY NON-EXPORTED VALUES BELOW HERE
